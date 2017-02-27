#!/usr/bin/env python
#encoding=utf-8

# from __future__ import print_function
# from __future__ import unicode_literals

import jieba
import re
import pinyin
import argparse

from datetime import tzinfo, timedelta, datetime

DFXPDocumentTemplate = """\
<?xml version="1.0" encoding="UTF-8"?>
<tt xml:lang='zh-CN' xmlns='http://www.w3.org/2006/10/ttaf1' xmlns:tts='http://www.w3.org/2006/10/ttaf1#style'>
<head>
      <styling>
        <style id="b1" tts:fontSize="10" tts:fontWeight="normal" tts:textAlign="left" tts:fontFamily="monospace" tts:color="#ffffff"/>
      </styling>
</head>
<body>
    <div xml:lang="en" xml:id="captions" style="b1">
    {captions}
    </div>
</body>
</tt>
"""

DFXPCaptionTemplate = """<p begin="{start_time}" end="{end_time}">{mandarin}<br />{pinyin}</p>"""

def tc2ms(tc):
    ''' convert timecode to millisecond '''

    sign    = 1
    if tc[0] in "+-":
        sign    = -1 if tc[0] == "-" else 1
        tc  = tc[1:]

    TIMECODE_RE     = re.compile('(?:(?:(?:(\d?\d):)?(\d?\d):)?(\d?\d))?(?:[,.](\d?\d?\d))?')
    # NOTE the above regex matches all following cases
    # 12:34:56,789
    # 01:02:03,004
    # 1:2:3,4   => 01:02:03,004
    # ,4        => 00:00:00,004
    # 3         => 00:00:03,000
    # 3,4       => 00:00:03,004
    # 1:2       => 00:01:02,000
    # 1:2,3     => 00:01:03,003
    # 1:2:3     => 01:02:03
    # also accept "." instead of "," as millsecond separator
    match   = TIMECODE_RE.match(tc)
    try:
        assert match is not None
    except AssertionError:
        print(tc)
    hh,mm,ss,ms = map(lambda x: 0 if x==None else int(x), match.groups())
    return ((hh*3600 + mm*60 + ss) * 1000 + ms) * sign

def ms2tc(ms):
    ''' convert millisecond to timecode '''
    sign    = '-' if ms < 0 else ''
    ms      = abs(ms)
    ss, ms  = divmod(ms, 1000)
    hh, ss  = divmod(ss, 3600)
    mm, ss  = divmod(ss, 60)
    TIMECODE_FORMAT = '%s%02d:%02d:%02d.%03d'
    return TIMECODE_FORMAT % (sign, hh, mm, ss, ms)

class Subtitle:
    line = int
    start_time = str
    end_time = str
    mandarin = str

    def __repr__(self):
        return "{self.line}: {self.mandarin} ({self.start_time} --> {self.end_time})".format(self=self)

def read_subtitles(filename):
    subtitle = Subtitle()
    TIMECODE_SEP    = re.compile('[ \->]*')
    with open(filename) as f:
        for i, text in enumerate(f.readlines()):
            if i % 4 == 0:
                subtitle.line = int(text)
            elif i % 4 == 1:
                subtitle.start_time, subtitle.end_time = map(tc2ms, TIMECODE_SEP.split(text.strip()))
                subtitle.start_time -= 6000
                subtitle.end_time -= 6000

            elif i % 4 == 2:
                subtitle.mandarin = text.strip()
            else:
                yield subtitle
                subtitle = Subtitle()

def time_shifted(subtitles, ms):
    for subtitle in subtitles:
        subtitle.start_time += ms
        subtitle.end_time += ms
        yield subtitle

def write_dfxp(subtitles):
    spacer = "·"
    captions = []

    subtitles = [s for s in subtitles]

    fake_last = Subtitle()
    fake_last.start_time = 1000 * 60 * 60 * 24 # for movies more than 24h this breaks the last subtitle
    subtitles.append(fake_last)

    for subtitle, next_subtitle in zip(subtitles, subtitles[1:]):
        mandarin_words = [w for w in jieba.cut(subtitle.mandarin)]
        pinyin_words = [pinyin.get(word) for word in mandarin_words]

        mandarin_line = ""
        mandarin_length = 0
        pinyin_line = ""
        pinyin_length = 0

        for mandarin_word, pinyin_word in zip(mandarin_words, pinyin_words):
            # XXX Something is weird with netflix. Not quite monospace
            # print(mandarin_line, mandarin_length)
            # print(pinyin_line, pinyin_length)

            if mandarin_length > pinyin_length:
                pinyin_line += spacer * (mandarin_length - pinyin_length)
                pinyin_length = mandarin_length
            elif pinyin_length > mandarin_length:
                mandarin_line += spacer * (pinyin_length - mandarin_length)
                mandarin_length = pinyin_length

            # print(mandarin_line, mandarin_length)
            # print(pinyin_line, pinyin_length)

            # print("adding ", mandarin_word, len(mandarin_word), pinyin_word, len(pinyin_word))


            mandarin_line += mandarin_word + ' '
            mandarin_length += len(mandarin_word) * 2 + 1

            pinyin_line += pinyin_word + ' '
            pinyin_length += len(pinyin_word) + 1

        captions.append(DFXPCaptionTemplate.format(start_time=ms2tc(subtitle.start_time),
                                                   end_time=ms2tc(next_subtitle.start_time-1),
                                                   mandarin=mandarin_line,
                                                   pinyin=pinyin_line))


    return DFXPDocumentTemplate.format(captions='\n'.join(captions))



def main():
    parser = argparse.ArgumentParser(description='Given a .srt file, annotate with pinyin and convert to .dfxp suitable for Netflix.')
    parser.add_argument('input', metavar='INPUT', type=str,
                       help='The subtitles file to annotate and convert')
    parser.add_argument('output', metavar='OUTPUT', type=str,
                       help='The output filename')
    parser.add_argument('--timeshift', metavar='MILLIS', type=int, default=0,
                       help='Shift by MILLIS milliseconds')
    args = parser.parse_args()

    print('Converting {args.input} to {args.output}, timeshifted by {args.timeshift} milliseconds'.format(args=args))
    subtitles = read_subtitles(args.input)
    subtitles = time_shifted(subtitles, args.timeshift)
    with open(args.output, 'w') as f:
        f.write(write_dfxp(subtitles))

if __name__ == '__main__':
    main()
