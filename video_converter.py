# -*- coding: utf-8 -*-
# !/usr/bin/python

import sys
import string
import getopt
import os
import os.path
import errno
import logging
import subprocess

import re
"""
-----------------------------------------------------------------------------
A script that will convert video files to multiple formats including flv, ogg,
mp4 (playable on ios), and webm.

This script assumes the server has all the required software.  Please follow
this guide to install everything.

https://ffmpeg.org/trac/ffmpeg/wiki/UbuntuCompilationGuide

The mediainfo command is used to gather information about the video file to be
converted, such as video width and height and frame rate, to allow good quality
conversion.  The ffmpeg command is used to do the actual conversion to different
video output formats.  Aspect ratios are kept and padding is applied to videos.

Video files can be converted individually or in batch.  There are options for
saving old files when converting individually. When batch converting videos, all
files under a given directory are assumed to be video files.  The converted
files can then be output to another directory keeping the same directory
structure.

Use the -h or the --help flag to get a listing of usage and options.

Program: Reprocess Videos
Author: Dennis E. Kubes
Date: February 04, 2012
Revision: 1.0

Revision      | Author            | Comment
-----------------------------------------------------------------------------
20120204-1.0   Dennis E. Kubes     Initial creation of script.
20130411-2.0   Dennis E. Kubes     Convert to HTML5 formats as well as flash.
-----------------------------------------------------------------------------
"""

# Configuration options, currently outputs 640x480 scaled, padded with a max
# video bitrate of 1024kbps and max audio bitrate of 56kbps.  If changing the
# size be sure to change the bitrates to match.
OUTPUTS = ["mp4"]  # ["ogv", "mp4", "webm"]
FFMPEG = "/usr/local/bin/ffmpeg"
MEDIAINFO = "/usr/bin/mediainfo"
VIDEO_WIDTH = 1280.0
VIDEO_HEIGHT = 720.0
MAX_VIDEO_BITRATE_KBPS = 1024
MAX_AUDIO_BITRATE_KBPS = 128
MAX_AUDIO_SAMPLING = 44100


class MediaInfo:
    """
    A class which retieves info about media files including the width, height,
    input format, and running time of videos.
    """

    def __init__(self, media_file):
        self.info = {}
        infocmd = [MEDIAINFO, media_file]
        output = subprocess.Popen(infocmd,
                                  stdout=subprocess.PIPE).communicate()[0]
        prefix = ""
        for line in output.split("\n"):
            if line and line.strip():
                if not ":" in line:
                    prefix = line.lower().strip()
                keyval = line.split(":")
                if len(keyval) == 2:
                    key = keyval[0].strip().lower().replace(" ", "_")
                    val = keyval[1].strip().lower()
                    self.info[prefix + "_" + key] = val

    def _get_stripped_value(self, label, value, regex=False):
        """
        Gets the value of the given value, and strips the label
        (units, eg.: pixels, fps, etc.)
        :param label: the units to strip from the value, a substring or regex
        :type label: str
        :param value: the 'key' to read from the media info output
        :type value: str
        :param regex: True if we are stripping the units from a regex
        :type regex: bool
        :return: the value of the label stripped without units
        :rtype: str
        """
        print self.info
        stripped = self.info.get(value)
        if stripped:
            if regex:
                stripped = re.sub(r'%s' % label, '', stripped)
            stripped = stripped.replace(label, "").replace(" ", "")
        return stripped

    def _get_bitrate_in_kbps(self, label):
        raw_value = self.info.get(label)
        if raw_value:
            if "kbps" in raw_value:
                value = self._get_stripped_value("kbps", label)
                return int(float(value))
            elif "mbps" in raw_value:
                value = self._get_stripped_value("mbps", label)
                value = int(float(value)) * 1024
                return value
        return None

    def get_width(self):
        value = self._get_stripped_value("pixels", "video_width")
        return int(value)

    def get_height(self):
        value = self._get_stripped_value("pixels", "video_height")
        return int(value)

    def get_frames_per_second(self):
        value = self._get_stripped_value("fps", "video_frame_rate")
        value = value.split('(')[0]
        return int(float(value))

    def get_duration(self):
        """
        Get the video duration in seconds
        :return: the duration in seconds
        :rtype: int
        """
        value = self._get_stripped_value("s(\W\d+ms){0,1}", "video_duration",
                                         regex=True)
        value = value.split('mn')
        if len(value) > 1:
            value = int(float(value[0]))*60 + int(float(value[1]))
        else:
            value = value[0]
        return int(float(value))

    def get_video_bitrate(self):
        return self._get_bitrate_in_kbps("video_bit_rate")

    def get_audio_bitrate(self):
        return self._get_bitrate_in_kbps("audio_bit_rate")

    def get_audio_sampling(self):
        label = "audio_sampling_rate"
        raw_value = self.info.get(label)
        if raw_value:
            if "khz" in raw_value:
                sampling = self._get_stripped_value("khz", label)
                sampling = int(float(sampling)) * 1024
                return sampling
            elif "hz" in raw_value:
                sampling = self._get_stripped_value("hz", label)
                return int(float(sampling))
        return None

    def __str__(self):
        infostr = ""
        for (key, value) in self.info.items():
            infostr += key + ": " + value + "\n"
        return infostr


class VideoConverter(object):
    """
    A class which converts video files from their original format to flash video
    format optimized for web viewing.
    """

    def __init__(self, video_file, output_dir=None, prefix=None, dry_run=False,
                 exists=False, backup=False, verbosity="verbose"):

        self.parent_dir = os.path.dirname(video_file)
        self.video_file = video_file
        self.output_dir = output_dir if output_dir else self.parent_dir
        self.prefix = prefix
        self.dry_run = dry_run
        self.exists = exists
        self.backup = backup
        self.max_width = VIDEO_WIDTH
        self.max_height = VIDEO_HEIGHT
        self.verbosity = verbosity
        self.do_resize = False

    def _command(self, params):
        if not self.dry_run:
            subprocess.check_call(params)

    def _get_convert_command(self, filetype, original, output, frame_rate,
                             video_bitrate, audio_bitrate, audio_sampling,
                             padscale):

        if filetype == "flv":
            params = [
                FFMPEG,
                "-i", original,
                "-vcodec", "flv",
                "-f", "flv",
                "-r", str(frame_rate),
                "-b:v", str(video_bitrate) + "k",
                "-g", "160",
                "-cmp", "dct",
                "-subcmp", "dct",
                "-mbd", "2",
                "-trellis", "1",
                "-ac", "1",
                "-ar", "22050",
                "-ab", str(audio_bitrate) + "k",
                "-v", self.verbosity]
            if self.do_resize:
                params += [
                    "-vf", padscale
                ]
            params += [output]
            return params

        elif filetype == "mp4":
            params = [
                FFMPEG,
                "-i", original,
                "-vcodec", "libx264",
                "-acodec", "libfdk_aac",
                "-preset", "slow",
                "-profile:v", "baseline",
                "-strict", "experimental",
                "-f", "mp4",
                "-r", str(frame_rate),
                "-b:v", str(video_bitrate) + "k",
                "-g", "160",
                "-cmp", "dct",
                "-subcmp", "dct",
                "-mbd", "2",
                "-trellis", "1",
                "-level", "30",
                "-ac", "2",
                "-ar", "22050",
                "-ab", str(audio_bitrate) + "k",
                "-maxrate", "10000000",
                "-bufsize", "10000000",
                "-threads", "0",
                "-pix_fmt", "yuv420p",
                "-v", self.verbosity]
            if self.do_resize:
                params += [
                    "-vf", padscale
                ]
            params += [output]
            return params

        elif filetype == "webm":
            params = [
                FFMPEG,
                "-i", original,
                "-vcodec", "libvpx",
                "-acodec", "libvorbis",
                "-f", "webm",
                "-r", str(frame_rate),
                "-b:v", str(video_bitrate) + "k",
                "-g", "160",
                "-cmp", "dct",
                "-subcmp", "dct",
                "-mbd", "2",
                "-trellis", "1",
                "-ac", "1",
                "-ar", str(audio_sampling),
                "-ab", str(audio_bitrate) + "k",
                "-v", self.verbosity]
            if self.do_resize:
                params += [
                    "-vf", padscale
                ]
            params += [output]
            return params

        elif filetype == "ogv":
            params = [
                FFMPEG,
                "-i", original,
                "-vcodec", "libtheora",
                "-acodec", "libvorbis",
                "-f", "ogg",
                "-r", str(frame_rate),
                "-b:v", str(video_bitrate) + "k",
                "-g", "160",
                "-cmp", "dct",
                "-subcmp", "dct",
                "-mbd", "2",
                "-trellis", "1",
                "-ac", "1",
                "-ar", str(audio_sampling),
                "-ab", str(audio_bitrate) + "k",
                "-v", self.verbosity]
            if self.do_resize:
                params += [
                    "-vf", padscale
                ]
            params += [output]
            return params


    def _get_thumb_commands(self, original, output):
        # ffmpeg -i input.flv -ss 00:00:14.435 -vframes 1 out.png
        mediainfo = MediaInfo(original)
        duration = mediainfo.get_duration()
        time_to_snapshot = duration / 2
        return [
            FFMPEG,
            "-ss", str(time_to_snapshot),
            "-i", original,
            "-frames:v", "1",
            output
        ]

    def _get_convert_commands(self, original, output):

        mediainfo = MediaInfo(original)
        width = mediainfo.get_width()
        height = mediainfo.get_height()
        fps = mediainfo.get_frames_per_second()
        video_bitrate = mediainfo.get_video_bitrate()
        audio_bitrate = mediainfo.get_audio_bitrate()
        audio_sampling = mediainfo.get_audio_sampling()

        # calculate the correct width and height for the aspect ratio
        resize_width = width
        resize_height = height
        if width > self.max_width or height > self.max_height:
            resize_width = width
            resize_height = height
            aspect_ratio = float(resize_width) / float(resize_height)
            if resize_width > self.max_width:
                resize_width = self.max_width
                resize_height = resize_width / aspect_ratio
                self.do_resize = True
            if resize_height > self.max_height:
                resize_height = self.max_height
                resize_width = resize_height * aspect_ratio
                self.do_resize = True

        # create the padscale options
        padscale = ("scale=%s:%s,pad=%s:%s:(ow-iw)/2:(oh-ih)/2:black" %
                    (int(resize_width), int(resize_height), int(self.max_width),
                     int(self.max_height)))

        # max high quality videos bitrate
        if not video_bitrate or video_bitrate > MAX_VIDEO_BITRATE_KBPS:
            video_bitrate = MAX_VIDEO_BITRATE_KBPS

        # max high quality audio bitrate
        if not audio_bitrate or audio_bitrate > MAX_AUDIO_BITRATE_KBPS:
            audio_bitrate = MAX_AUDIO_BITRATE_KBPS

        # max high quality audio sampling
        if not audio_sampling or audio_sampling > MAX_AUDIO_SAMPLING:
            audio_sampling = MAX_AUDIO_SAMPLING

        # get all file type conversion commands
        commands = []
        for filetype in OUTPUTS:
            tmpfile = output + ".tmp." + filetype
            commands.append(
                (filetype, self._get_convert_command(filetype, original,
                                                     os.path.join(
                                                         self.parent_dir,
                                                         tmpfile), fps,
                                                     video_bitrate,
                                                     audio_bitrate,
                                                     audio_sampling, padscale)))

        return commands

    def convert_video(self):

        vparts = os.path.basename(self.video_file).split(".")
        vparts.pop(len(vparts) - 1)
        name = '.'.join(vparts)
        name = self.prefix + name if self.prefix else name
        final_paths = []
        try:
            # create the output directory structure if needed
            if not os.path.exists(self.output_dir):
                logging.info(
                    "Creating output directory: %s" % self.output_dir)
                self._command(["mkdir", "-p", self.output_dir])

            # convert the original video into each of the different
            # output formats
            # name = self.prefix + vparts[0] if self.prefix else vparts[0]
            convertcmds = self._get_convert_commands(self.video_file, name)
            for (extension, convertcmd) in convertcmds:

                # file names
                extname = name + "." + extension
                tmpname = name + ".tmp." + extension

                # full file paths
                extfile = os.path.join(self.parent_dir, extname)
                tmpfile = os.path.join(self.parent_dir, tmpname)

                final_path = os.path.join(self.output_dir, extname)
                final_bak = os.path.join(self.output_dir, extname + ".bak")

                # skip conversion if the exists flag is set and the file
                # exists
                if self.exists and os.path.exists(final_path):
                    logging.info(
                        "Skipping conversion of existing file %s" %
                        final_path)
                    continue

                # convert the video using ffmpeg
                logging.info("Conversion: %s" % " ".join(convertcmd))
                self._command(convertcmd)

                # perform backup if needed
                if os.path.exists(final_path) and self.backup:

                    # if there an existing backup file, remove it, this
                    # means it was previously converted and backed up
                    if os.path.exists(final_bak):
                        logging.info("Removing backup: %s" % final_bak)
                        self._command(["rm", "-f", final_bak])

                    # move the existing old video to
                    logging.info("Backup existing: %s -> %s" % (final_path,
                                                                final_bak))
                    self._command(["mv", final_path, final_bak])

                # move the converted video file to its final location
                logging.info(
                    "Moving output: %s -> %s" % (tmpfile, final_path))
                self._command(["mv", tmpfile, final_path])
                final_paths.append(final_path)

        except Exception:
            logging.exception("Error converting: %s" % self.video_file)
        else:
            print final_paths
            return final_paths

    def get_thumbnail(self):
        thumb_path = ''
        vparts = os.path.basename(self.video_file).split(".")

        #try:
        # create the output directory structure if needed
        if not os.path.exists(self.output_dir):
            logging.info(
                "Creating output directory: %s" % self.output_dir)
            self._command(["mkdir", "-p", self.output_dir])
        vparts.pop(len(vparts)-1)
        name = '.'.join(vparts)
        name = self.prefix + name if self.prefix else name
        extname = name + ".jpg"
        final_path = os.path.join(self.output_dir, extname)
        thumbcmd = self._get_thumb_commands(self.video_file, final_path)
        if self.exists and os.path.exists(final_path):
            logging.info(
                "Skipping conversion of existing file %s" %
                final_path)
            return final_path
        logging.info("Generating thumb: %s" % " ".join(thumbcmd))
        self._command(thumbcmd)
        thumb_path = final_path
        # logging.info(
        #     "Moving output: %s -> %s" % (tmpfile, final_path))
        # self._command(["mv", tmpfile, final_path])
        #except Exception, e:
        #    print "unable to generate thumbnail:", e.message

        return thumb_path


class BatchConverter:
    """
    A class which converts all video files within a directory tree to flash
    video format optimized for web viewing.
    """

    def __init__(self, input_dir=None, output_dir=None, prefix=None,
                 dry_run=False, exists=False, backup=False,
                 verbosity="verbose"):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.prefix = prefix
        self.dry_run = dry_run
        self.exists = exists
        self.backup = backup
        self.verbosity = verbosity

    def convert_all_videos(self):

        # keep only non-flv files to be converted, ignore . and .. dirs
        all_files = \
            [(parent, folders, files) for parent, folders, files in
             os.walk(self.input_dir)]
        videos = []
        for f in all_files:
            parent_dir = f[0]
            for filename in f[2]:
                fparts = filename.split(".")
                if len(fparts) == 2:
                    video_file = os.path.join(parent_dir, filename)
                    videos.append(video_file)

        # sort the video filenames to have a consistent conversion sequence
        videos.sort()

        # convert the videos to html5 and flash
        num_videos = len(videos)
        for (index, video) in enumerate(videos):

            # setup the final output directory
            final_dir = self.output_dir
            if final_dir is not None:
                original_path = os.path.dirname(video)
                final_dir = original_path.replace(self.input_dir, final_dir, 1)

            # convert the video
            print("Converting %s of %s: %s" % (index + 1, num_videos, video))
            logging.info(
                "Starting %s of %s: %s" % (index + 1, num_videos, video))
            converter = VideoConverter(video, final_dir, self.prefix,
                                       self.dry_run,
                                       self.exists, self.backup, self.verbosity)
            converter.convert_video()
            logging.info("Finsished %s of %s" % (index + 1, num_videos))


def usage():
    """
    Prints out the usage for the command line.
    """
    lib_usage = ["flash_converter.py [-hitpfdebvg]\n",
                 "  [-h | --help] prints this help and usage message\n",
                 "  [-i | --input-dir] the video input root directory.\n",
                 "  [-t | --output-dir] the video output directory.\n",
                 "  [-p | --prefix] a filename prefix for video outputs.\n",
                 "  [-f | --input-file] the input video file to convert\n",
                 "  [-d | --dry-run] dry run, print commands, don't convert\n",
                 "  [-e | --exists] ignore file if output already exists.\n",
                 "  [-b | --backup] backup old videos, rename to *.bak\n",
                 "  [-v | --verbosity] the verbosity level, quiet to debug\n",
                 "  [-g | --logfile] the conversion logfile\n"]
    message = string.join(lib_usage)
    print message


def main(argv):
    """
    Main method that starts up the backup.
    """
    # set the default values
    input_dir = None
    output_dir = None
    prefix = None
    video_file = None
    dry_run = False
    exists = False
    backup = False
    verbosity = "verbose"

    try:

        # process the command line options
        opts, args = getopt.getopt(argv, "hi:t:p:f:debv:g:",
                                   ["help", "input-dir=",
                                    "output-dir=", "output-prefix=", "file=",
                                    "dry-run", "exists", "backup",
                                    "verbosity=", "logfile="])

        # if no arguments print usage
        if len(argv) == 0:
            usage()
            sys.exit()

            # loop through all of the command line options and set the
            # appropriate
        # values, overriding defaults
        for opt, arg in opts:
            if opt in ("-h", "--help"):
                usage()
                sys.exit()
            elif opt in ("-i", "--input-dir"):
                input_dir = os.path.abspath(arg)
            elif opt in ("-t", "--output-dir"):
                output_dir = os.path.abspath(arg)
            elif opt in ("-p", "--prefix"):
                prefix = arg
            elif opt in ("-f", "--file"):
                video_file = os.path.abspath(arg)
            elif opt in ("-d", "--dry-run"):
                dry_run = True
            elif opt in ("-e", "--exists"):
                exists = True
            elif opt in ("-b", "--backup"):
                backup = True
            elif opt in ("-v", "--verbosity"):
                verbosity = arg
            elif opt in ("-g", "--logfile"):
                logging.basicConfig(filename=arg, level=logging.INFO)

    except getopt.GetoptError, msg:
        print(msg)
        # if an error happens print the usage and exit with an error
        usage()
        sys.exit(errno.EIO)

    # check options are set correctly
    batch = input_dir and os.path.exists(input_dir)
    single = video_file and os.path.exists(video_file)
    if not batch and not single:
        print("A root directory or a single video file is required for "
              "conversion")
        usage()
        sys.exit(errno.EPERM)

    # create the converter object and call its convert method
    if batch:
        converter = BatchConverter(input_dir, output_dir, prefix, dry_run,
                                   exists, backup, verbosity)
        converter.convert_all_videos()
    elif single:
        converter = VideoConverter(video_file, output_dir, prefix, dry_run,
                                   exists, backup, verbosity)
        converter.convert_video()

        # if we are running the script from the command line, run the main method


if __name__ == "__main__":
    main(sys.argv[1:])
