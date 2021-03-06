import tensorflow as tf
from tensorflow.contrib.learn.python.learn.preprocessing import text
import numpy as np
import data_dealer

tf.flags.DEFINE_integer("epoch_size",10,"Default 10")
tf.flags.DEFINE_integer("batch_size",300,"Default 300")
tf.flags.DEFINE_integer("evaluate_step",50,"Evaluate each 50[default] global steps")
tf.flags.DEFINE_integer("embedding_size",200,"Default 200")
tf.flags.DEFINE_integer("hidden_size",64,"Default 64")
tf.flags.DEFINE_float("dropout_keep_probability",0.9,"Probability of keep neuron, default 0.9")
tf.flags.DEFINE_integer("topic_num",3,"The number of different news topics, it depends on news corpus.")
tf.flags.DEFINE_bool("shuffle_input",True,"Default True")
tf.flags.DEFINE_float("train_dev_split_ratio",0.98,"Default 0.01, 98% is training data, 2% is development data")

FLAGS=tf.flags.FLAGS
FLAGS._parse_flags()

for para,val in FLAGS.__flags.items():
    print("parameter %s: %s"%(para,val))


class topicRNN(object):
    def __init__(self, vocabulary_size, embedding_size, hidden_size, max_news_size, topic_size):
        #input information
        self.input_news=tf.placeholder(tf.int64, [None, max_news_size], name='input_news')
        self.input_topic=tf.placeholder(tf.int64, [None], name='input_topic')
        self.early_stop=tf.placeholder(tf.int32, [None],name='early_stop')
        self.dropout_keep_probability=tf.placeholder(tf.float32, name='dropout_keep_probability')
        #embedding size, notice that GPU cannot used in embedding.
        with tf.device('/cpu:0'), tf.name_scope('embedding'):
            embedding_matrix=tf.Variable(tf.random_uniform([vocabulary_size,embedding_size],-1,1), name='embed_matrix')
            #self.embedding_news : [None(batch_size), max_news_size, embedding_size]
            self.embedding_news=tf.nn.embedding_lookup(embedding_matrix,self.input_news)
        batch_size=tf.shape(self.embedding_news)[0]
        self.X= tf.transpose(self.embedding_news,[1,0,2])
        self.X= tf.reshape(self.X,[-1,embedding_size])
        #Splits a tensor into num_split tensors along one dimension
        #a list of 'time_steps' tensors of shape (batch_size, embedding_size)
        self.X= tf.split(0,max_news_size,self.X)
        lstm_cell=tf.nn.rnn_cell.BasicLSTMCell(hidden_size)
        outputs,states=tf.nn.rnn(lstm_cell,self.X,dtype=tf.float32,sequence_length=None)
        # 'outputs' is a list of output at every timestep
        # pack them in a Tensor
        outputs = tf.pack(outputs)
        #[None(batch_size), max_news_size, hidden_size]
        outputs = tf.transpose(outputs, [1, 0, 2])
        #only the last output in one news is important
        batch_size=tf.shape(outputs)[0]
        index=tf.range(0, batch_size)*max_news_size+self.early_stop
        #[None(batch_size), hidden_size]
        outputs=tf.gather(tf.reshape(outputs,[-1,hidden_size]),index)
        
        with tf.name_scope('drop_out'):
            outputs=tf.nn.dropout(outputs,self.dropout_keep_probability)
        
        
        #unnormalized scores and prediction
        with tf.name_scope('output'):
            w=tf.Variable(tf.truncated_normal([hidden_size,topic_size],stddev=0.1),name='w')
            b=tf.Variable(tf.constant(0.1,shape=[topic_size]),name='b')
            self.scores=tf.nn.xw_plus_b(outputs,w,b,name='scores')
            self.prediction=tf.argmax(self.scores,1,name='prediction')
        
        #loss
        with tf.name_scope('loss'):
            losses=tf.nn.sparse_softmax_cross_entropy_with_logits(self.scores, self.input_topic)
            self.loss=tf.reduce_mean(losses,name='loss')
            
        #accuracy
        with tf.name_scope('accuracy'):
            correct_pre=tf.equal(self.prediction,self.input_topic)
            self.accuracy=tf.reduce_mean(tf.cast(correct_pre,'float'),name='accuracy')


print("Loading news and topic...")
all_urls, all_titles, all_news=data_dealer.import_data()
#data is a dictionary, comprised of health, auto, business, it, sports, learning, news, yule 10001 respectively.
data=data_dealer.subData(all_urls, all_titles, all_news)
health=zip(data['health'],np.ones([10001,1]))
auto=zip(data['auto'],2*np.ones([10001,1]))
business=zip(data['business'],3*np.ones([10001,1]))
x_news=data['health']+data['auto']+data['business']
y_label=[0]*10001+[1]*10001+[2]*10001


from tensorflow.contrib import learn
early_stop_index=np.array([len(x.split(" "))-1 for x in x_news])
max_news_length=max(early_stop_index)
words_to_num=learn.preprocessing.VocabularyProcessor(max_news_length)
print('Maximal length in all news: %s' % max_news_length)
x_nums=np.array(list(words_to_num.fit_transform(x_news)))
vocabulary_size=len(words_to_num.vocabulary_)
print("There are %s Chinese vocabulary in all the news corpus." % vocabulary_size)
#processor.reverse(res)


if FLAGS.shuffle_input:
    print("Shuffle input data...")
    np.random.seed(1)
    new_indices=np.random.permutation(range(len(y_label)))
    x_nums=x_nums[new_indices]
    y_label=np.array(y_label)[new_indices]
    early_stop_index=early_stop_index[new_indices]

print("Split input data into training and development part...")
x_train=x_nums[:FLAGS.train_dev_split_ratio*len(y_label),:]
y_train=y_label[:FLAGS.train_dev_split_ratio*len(y_label)]
early_stop_index_train=early_stop_index[:FLAGS.train_dev_split_ratio*len(y_label)]
x_dev=x_nums[FLAGS.train_dev_split_ratio*len(y_label):,:]
y_dev=y_label[FLAGS.train_dev_split_ratio*len(y_label):]
early_stop_index_dev=early_stop_index[FLAGS.train_dev_split_ratio*len(y_label):]

print("---------------Start training RNN model...--------------------")
gra=tf.Graph()
with gra.as_default():
    sess=tf.Session()
    with sess.as_default():   
        rnn=topicRNN(vocabulary_size=vocabulary_size,embedding_size=FLAGS.embedding_size,
                         hidden_size=FLAGS.hidden_size,
                         max_news_size=max_news_length,topic_size=3)
        print('RNN Model has been built!')
        global_step=tf.Variable(0,name="global_step",trainable=False)
        optimizer=tf.train.AdamOptimizer(learning_rate=0.1)
        gradient_and_variable=optimizer.compute_gradients(rnn.loss)
        train_op=optimizer.apply_gradients(gradient_and_variable,global_step=global_step)
        
        sess.run(tf.initialize_all_variables())
        
        def train_one_step(x_batch,y_batch,early_stop_batch):
            feed_dict={rnn.input_news:x_batch,rnn.input_topic:y_batch,
                       rnn.dropout_keep_probability:FLAGS.dropout_keep_probability,
                       rnn.early_stop:early_stop_batch}
            _,step,loss,accuracy=sess.run([train_op,global_step,rnn.loss,rnn.accuracy],feed_dict)
            print("Train processing: step {}, loss {}, accuracy {}".format(step,loss,accuracy))
        
        def dev_one_step(x_batch,y_batch,early_stop_batch):
            feed_dict={rnn.input_news:x_batch,rnn.input_topic:y_batch,
                       rnn.dropout_keep_probability:1.0,rnn.early_stop:early_stop_batch}
            step,loss,accuracy=sess.run([global_step,rnn.loss,rnn.accuracy],feed_dict)
            print("Dev processing: step {}, loss {}, accuracy {}".format(step,loss,accuracy))
        
        
        for epo in range(FLAGS.epoch_size):
            print('---------------Epoch: %s---------------' % epo)
            # input data in each epoch is not be permutated!
            for i in range(len(y_train)//FLAGS.batch_size):
                x_temp=x_train[i*FLAGS.batch_size:(i+1)*FLAGS.batch_size]
                y_temp=y_train[i*FLAGS.batch_size:(i+1)*FLAGS.batch_size]
                early_stop_temp=early_stop_index_train[i*FLAGS.batch_size:(i+1)*FLAGS.batch_size]
                train_one_step(x_temp,y_temp,early_stop_temp)
                current_step=tf.train.global_step(sess,global_step)
                if current_step % FLAGS.evaluate_step==0:
                    print("Evalution start... at step %s"%current_step)
                    dev_one_step(x_dev,y_dev,early_stop_index_dev)
                    print("Evaluation end")

