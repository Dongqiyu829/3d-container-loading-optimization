import tensorflow as tf
#输出显示测试安装结果
print(tf.__version__)
import keras
print(keras.__version__)
print('GPU',tf.test.is_gpu_available())
gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
print(gpus)
