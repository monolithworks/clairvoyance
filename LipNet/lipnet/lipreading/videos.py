import math
import time
import os
import numpy as np
from keras import backend as K
from scipy import ndimage
from scipy.misc import imresize
import skvideo.io
import cv2
import dlib
from lipnet.lipreading.aligns import Align

class VideoAugmenter(object):
    @staticmethod
    def split_words(video, align):
        video_aligns = []
        for sub in align.align:
            # Create new video
            _video = Video(video.vtype, video.face_predictor_path)
            _video.face = video.face[sub[0]:sub[1]]
            _video.mouth = video.mouth[sub[0]:sub[1]]
            _video.set_data(_video.mouth)
            # Create new align
            _align = Align(align.absolute_max_string_len, align.label_func).from_array([(0, sub[1]-sub[0], sub[2])])
            # Append
            video_aligns.append((_video, _align))
        return video_aligns

    @staticmethod
    def merge(video_aligns):
        vsample = video_aligns[0][0]
        asample = video_aligns[0][1]
        video = Video(vsample.vtype, vsample.face_predictor_path)
        video.face = np.ones((0, vsample.face.shape[1], vsample.face.shape[2], vsample.face.shape[3]), dtype=np.uint8)
        video.mouth = np.ones((0, vsample.mouth.shape[1], vsample.mouth.shape[2], vsample.mouth.shape[3]), dtype=np.uint8)
        align = []
        inc = 0
        for _video, _align in video_aligns:
            video.face = np.concatenate((video.face, _video.face), 0)
            video.mouth = np.concatenate((video.mouth, _video.mouth), 0)
            for sub in _align.align:
                _sub = (sub[0]+inc, sub[1]+inc, sub[2])
                align.append(_sub)
            inc = align[-1][1]
        video.set_data(video.mouth)
        align = Align(asample.absolute_max_string_len, asample.label_func).from_array(align)
        return (video, align)

    @staticmethod
    def pick_subsentence(video, align, length):
        split = VideoAugmenter.split_words(video, align)
        start = np.random.randint(0, align.word_length - length)
        return VideoAugmenter.merge(split[start:start+length])

    @staticmethod
    def pick_word(video, align):
        video_aligns = np.array(VideoAugmenter.split_words(video, align))
        return video_aligns[np.random.randint(video_aligns.shape[0], size=2), :][0]

    @staticmethod
    def horizontal_flip(video):
        _video = Video(video.vtype, video.face_predictor_path)
        _video.face = np.flip(video.face, 2)
        _video.mouth = np.flip(video.mouth, 2)
        _video.set_data(_video.mouth)
        return _video

    @staticmethod
    def temporal_jitter(video, probability):
        changes = [] # [(frame_i, type=del/dup)]
        t = video.length
        for i in range(t):
            if np.random.ranf() <= probability/2:
                changes.append((i, 'del'))
            if probability/2 < np.random.ranf() <= probability:
                changes.append((i, 'dup'))
        _face = np.copy(video.face)
        _mouth = np.copy(video.mouth)
        j = 0
        for change in changes:
            _change = change[0] + j
            if change[1] == 'dup':
                _face = np.insert(_face, _change, _face[_change], 0)
                _mouth = np.insert(_mouth, _change, _mouth[_change], 0)
                j = j + 1
            else:
                _face = np.delete(_face, _change, 0)
                _mouth = np.delete(_mouth, _change, 0)
                j = j - 1
        _video = Video(video.vtype, video.face_predictor_path)
        _video.face = _face
        _video.mouth = _mouth
        _video.set_data(_video.mouth)
        return _video

    @staticmethod
    def pad(video, length):
        pad_length = max(length - video.length, 0)
        video_length = min(length, video.length)
        face_padding = np.ones((pad_length, video.face.shape[1], video.face.shape[2], video.face.shape[3]), dtype=np.uint8) * 0
        mouth_padding = np.ones((pad_length, video.mouth.shape[1], video.mouth.shape[2], video.mouth.shape[3]), dtype=np.uint8) * 0
        _video = Video(video.vtype, video.face_predictor_path)
        _video.face = np.concatenate((video.face[0:video_length], face_padding), 0)
        _video.mouth = np.concatenate((video.mouth[0:video_length], mouth_padding), 0)
        _video.set_data(_video.mouth)
        return _video


class Video(object):
    def __init__(self, vtype='mouth', face_predictor_path=None, preview=False):
        if vtype == 'face' and face_predictor_path is None:
            raise AttributeError('Face video need to be accompanied with face predictor')
        self.face_predictor_path = face_predictor_path
        self.vtype = vtype
        self.preview = preview
        self.framerate = None

    def from_frames(self, path, framerate=25):
        self.framerate = framerate
        frames_path = sorted([os.path.join(path, x) for x in os.listdir(path)])
        frames = [ndimage.imread(frame_path) for frame_path in frames_path]
        self.handle_type(frames)
        return self

    def from_video(self, path):
        self.framerate = self.get_frame_rate(path)
        frames = self.get_video_frames(path)
        self.handle_type(frames)
        return self

    def from_array(self, frames, framerate=25):
        self.framerate = framerate
        self.handle_type(frames)
        return self

    def handle_type(self, frames):
        if self.vtype == 'mouth':
            self.process_frames_mouth(frames)
        elif self.vtype == 'face':
            self.process_frames_face(frames)
        else:
            raise Exception('Video type not found')

    def get_frames_mouth(self, detector, predictor, frames):
        return self.mouth_frames_of_a_face(detector, predictor, frames)

    def get_frame_rate(self, path):
        frtxt = skvideo.io.ffprobe(path)['video']['@r_frame_rate']
        s = frtxt.split('/')
        if len(s) > 1:
            return float(s[0])/float(s[1])
        else:
            return float(s[0])

    def mouth_frames_of_a_face(self, detector, predictor, frames):
        frameskip = 0
        mouth_frames = []
        for frame in frames:
            if frameskip:
                frameskip = max(0, frameskip - 1)
            began_at = time.time()
            if self.preview and not frameskip:
                showframe = frame.copy()
            dets = detector(frame, 1)
            shape = None
            for k, d in enumerate(dets):
                shape = predictor(frame, d)
                if self.preview and not frameskip:
                    cv2.rectangle(showframe, (shape.rect.tl_corner().x, shape.rect.tl_corner().y), (shape.rect.br_corner().x, shape.rect.br_corner().y), (255,0,0), 2)
            if shape is None: # Detector doesn't detect face, interpolate with the last frame
                try:
                    mouth_frames.append(mouth_frames[-1])
                except IndexError:
                    raise NotImplementedError()
            else:
                mouth_frames.append(self.mouth_frame_of_face_shaped(shape, frame))
            elapsed = time.time() - began_at
            if self.preview and not frameskip:
                deadline = 1000/self.framerate
                slack = int(deadline - elapsed*1000)
                if slack < 0:
                    frameskip = math.ceil(-slack / deadline)
                cv2.imshow('Video', cv2.cvtColor(showframe, cv2.COLOR_RGB2BGR))
                cv2.waitKey(max(1, slack))
        return mouth_frames

    def mouth_frame_of_face_shaped(self, shape, frame):
        MOUTH_WIDTH = 100
        MOUTH_HEIGHT = 50
        HORIZONTAL_PAD = 0.19
        normalize_ratio = None
        i = -1

        mouth_points = []
        for part in shape.parts():
            i += 1
            if i < 48: # Only take mouth region
                continue
            mouth_points.append((part.x,part.y))
        np_mouth_points = np.array(mouth_points)

        mouth_centroid = np.mean(np_mouth_points[:, -2:], axis=0)

        if normalize_ratio is None:
            mouth_left = np.min(np_mouth_points[:, :-1]) * (1.0 - HORIZONTAL_PAD)
            mouth_right = np.max(np_mouth_points[:, :-1]) * (1.0 + HORIZONTAL_PAD)

            normalize_ratio = MOUTH_WIDTH / float(mouth_right - mouth_left)

        new_img_shape = (int(frame.shape[0] * normalize_ratio), int(frame.shape[1] * normalize_ratio))
        resized_img = imresize(frame, new_img_shape)

        mouth_centroid_norm = mouth_centroid * normalize_ratio

        mouth_l = int(mouth_centroid_norm[0] - MOUTH_WIDTH / 2)
        mouth_r = int(mouth_centroid_norm[0] + MOUTH_WIDTH / 2)
        mouth_t = int(mouth_centroid_norm[1] - MOUTH_HEIGHT / 2)
        mouth_b = int(mouth_centroid_norm[1] + MOUTH_HEIGHT / 2)

        return resized_img[mouth_t:mouth_b, mouth_l:mouth_r]

    def process_frames_face(self, frames):
        detector = dlib.get_frontal_face_detector()
        predictor = dlib.shape_predictor(self.face_predictor_path)
        mouth_frames = self.get_frames_mouth(detector, predictor, frames)
        self.face = np.array(frames)
        self.mouth = np.array(mouth_frames)
        self.set_data(mouth_frames)

    def process_frames_mouth(self, frames):
        self.face = np.array(frames)
        self.mouth = np.array(frames)
        self.set_data(frames)

    def get_video_frames(self, path):
        videogen = skvideo.io.vreader(path)
        frames = np.array([frame for frame in videogen])
        return frames

    def set_data(self, frames):
        data_frames = []
        for frame in frames:
            frame = frame.swapaxes(0,1) # swap width and height to form format W x H x C
            if len(frame.shape) < 3:
                frame = np.array([frame]).swapaxes(0,2).swapaxes(0,1) # Add grayscale channel
            data_frames.append(frame)
        frames_n = len(data_frames)
        data_frames = np.array(data_frames) # T x W x H x C
        if K.image_data_format() == 'channels_first':
            data_frames = np.rollaxis(data_frames, 3) # C x T x W x H
        self.data = data_frames
        self.length = frames_n
