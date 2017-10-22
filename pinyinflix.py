#!/usr/bin/env python
#encoding=utf-8

# from __future__ import print_function
# from __future__ import unicode_literals

import jieba
import re
import pinyin
import argparse
from collections import defaultdict
import json
import cedict
from googletrans import Translator
translator = Translator()
import time

from datetime import tzinfo, timedelta, datetime

google_translations = {}
with open('google_dict') as f:
    for line in f.readlines():
        chinese, english = line.split('\t')
        google_translations[chinese.strip()] = english.strip()
    print('loaded {} translations'.format(len(google_translations)))


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

cc_cedict = {}
with open('cedict_1_0_ts_utf-8_mdbg_20171013_060147.txt') as f:
    for ch, chs, p, defs, variants, mw in cedict.iter_cedict(f):
        if ch in ['曹军']:
            print(ch, chs, p, defs, variants, mw)
        try:
            cc_cedict[chs] = cc_cedict[chs].union(set(defs))
        except KeyError:
            cc_cedict[chs] = set(defs)

        try:
            cc_cedict[ch] = cc_cedict[ch].union(set(defs))
        except KeyError:
            cc_cedict[ch] = set(defs)

for key in cc_cedict:
    cc_cedict[key] = ' | '.join(cc_cedict[key])

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
    mandarin = ''

    def __repr__(self):
        return "{self.line}: {self.mandarin} ({self.start_time} --> {self.end_time})".format(self=self)

class States:
    NUMBER = 'number'
    TIME = 'time'
    TEXT = 'text'
    BLANK = 'blank'

def read_subtitles(filename):
    subtitle = Subtitle()
    TIMECODE_SEP    = '-->'
    with open(filename, encoding="utf-8") as f:
        state = States.BLANK
        for i, text in enumerate(f.read().split('\n')):
            # print(text)
            if state == States.BLANK:
                if text.strip() == '':
                    continue
                else:
                    subtitle.line = int(text)
                    state = States.NUMBER
            elif state == States.NUMBER:
                subtitle.start_time, subtitle.end_time = map(tc2ms, text.split(TIMECODE_SEP))
                subtitle.timecode = text
                state = States.TIME
            elif state == States.TIME:
                subtitle.mandarin += text.strip()
                state = States.TEXT
            elif state == States.TEXT:
                if text.strip() == '':
                    yield subtitle
                    subtitle = Subtitle()
                    state = States.BLANK
                else:
                    subtitle.mandarin += text.strip()

def time_shifted(subtitles, ms):
    for subtitle in subtitles:
        subtitle.start_time += ms
        subtitle.end_time += ms
        if subtitle.start_time <= 0:
            print(subtitle)
            print('skipping subtitle less than 0')
            continue
        yield subtitle

def get_line(subtitle, frequencies):
    mandarin_words = [w for w in jieba.cut(subtitle.mandarin)]
    pinyin_words = [pinyin.get(word) for word in mandarin_words]

    spacer = "·"

    mandarin_line = ""
    mandarin_length = 0
    pinyin_line = ""
    pinyin_length = 0

    for mandarin_word, pinyin_word in zip(mandarin_words, pinyin_words):
        frequencies[mandarin_word] += 1

        if mandarin_length > pinyin_length:
            pinyin_line += spacer * (mandarin_length - pinyin_length)
            pinyin_length = mandarin_length
        elif pinyin_length > mandarin_length:
            mandarin_line += spacer * (pinyin_length - mandarin_length)
            mandarin_length = pinyin_length

        # print("adding ", mandarin_word, len(mandarin_word), pinyin_word, len(pinyin_word))


        mandarin_line += mandarin_word + ' '
        mandarin_length += len(mandarin_word) * 2 + 1

        pinyin_line += pinyin_word + ' '
        pinyin_length += len(pinyin_word) + 1

    return mandarin_line, pinyin_line, mandarin_words

def get_translation(w, f):
    if w.strip() == '':
        return ''

    try:
        return cc_cedict[w]
    except KeyError:
        if w in google_translations:
            return google_translations[w]
        else:
            print('fetching translation for {}'.format(w))
            google_translations[w] = translator.translate(w, dest='en').text
            f.write('{}\t{}\n'.format(w, google_translations[w]))
            time.sleep(1)
            return google_translations[w]


def write_srt(subtitles):
    srt_template = '''{i}\n{start_time} --> {end_time}\n{colored_lines}\n'''
    line_template = '''{pinyin}\\N{mandarin}\\N{i}\\h'''
    color_template = '''<font color="{color}">{line}</font>\n'''

    frequencies = defaultdict(int)
    captions = []
    subtitles = list(subtitles)
    translations = []

    fake_last = Subtitle()
    fake_last.start_time = 1000 * 60 * 60 * 24 # for movies more than 24h this breaks the last subtitle
    subtitles.append(fake_last)

    f = open('google_dict', 'a')

    colors = ['#ffffff', '#aaaaaa', '#888888']
    onscreen_subtitles = {
        0: '',
        1: '',
        2: '',
    }

    next_line = 2

    for i, (subtitle, next_subtitle) in enumerate(zip(subtitles, subtitles[1:])):
        mandarin_line, pinyin_line, mandarin_words = get_line(subtitle, frequencies)
        subtitle_translations = ['{} {}: {}'.format(word, pinyin.get(word), get_translation(word, f)) for word in mandarin_words if get_translation(word, f)]

        if next_line == 0:
            colors = ['#ffffff', '#888888', '#aaaaaa']
        elif next_line == 1:
            colors = ['#aaaaaa', '#ffffff', '#888888']
        if next_line == 2:
            colors = ['#888888', '#aaaaaa', '#ffffff']

        onscreen_subtitles[next_line] = line_template.format(i=i, mandarin=mandarin_line, pinyin=pinyin_line)

        caption = ''
        caption += color_template.format(color=colors[0], line=onscreen_subtitles[0])
        caption += color_template.format(color=colors[1], line=onscreen_subtitles[1])
        caption += color_template.format(color=colors[2], line=onscreen_subtitles[2])

        next_line -= 1
        if next_line < 0: next_line = 2

        captions.append(srt_template.format(i=i,
                                            colored_lines=caption,
                                            start_time=ms2tc(subtitle.start_time),
                                            end_time=ms2tc(next_subtitle.start_time-1)))

        translations.append('''{i}\n{t}\n\n'''.format(i=i, t='\n'.join(subtitle_translations)))

    return '\n'.join(captions), frequencies, translations


def write_dfxp(subtitles):
    spacer = "·"
    captions = []

    subtitles = list(subtitles)

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

        print(mandarin_words, pinyin_words)

        for mandarin_word, pinyin_word in zip(mandarin_words, pinyin_words):
            # XXX Something is weird with netflix. Not quite monospace
            # print(mandarin_line, mandarin_length)
            # print(pinyin_line, pinyin_length)

            # print(mandarin_line, mandarin_length)
            # print(pinyin_line, pinyin_length)

            # print("adding ", mandarin_word, len(mandarin_word), pinyin_word, len(pinyin_word))


            mandarin_line += mandarin_word + ' '
            mandarin_length += len(mandarin_word) * 2 + 1

            pinyin_line += pinyin_word + ' '
            pinyin_length += len(pinyin_word) + 1

            if mandarin_length > pinyin_length:
                pinyin_line += spacer * (mandarin_length - pinyin_length)
                pinyin_length = mandarin_length
            elif pinyin_length > mandarin_length:
                mandarin_line += spacer * (pinyin_length - mandarin_length)
                mandarin_length = pinyin_length

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
    captions, frequencies, translations = write_srt(subtitles)

    with open(args.output, 'w') as f:
        f.write(captions)

    with open(args.output + '.freq', 'w') as f:
        for word, freq in sorted(frequencies.items(), key=lambda x: x[1], reverse=True):
            translation = get_translation(word, None)
            if word.strip() == '':
                continue
            f.write('{}\t{}\t{}\t{}\n'.format(freq, word, pinyin.get(word), translation))

    with open(args.output + '.translations', 'w') as f:
        f.write('\n'.join(translations))



if __name__ == '__main__':
    main()
