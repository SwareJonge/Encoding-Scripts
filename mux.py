import os
import json
from subprocess import run

# This hasn't been properly tested, this mostly resembles what i use in most of my projects

# I'm way too lazy to add actual xml writing, so just do it the jank way

def merge_chunks(chunk_count: int, work_dir: str, out_path: str, extra_commands: str):
    video_sources_cmd = f"( {work_dir}/chunks/0.ivf )" # the base chunk
    append_cmd = f"--append-to "

    for i in range(chunk_count-1):
        cur_idx = i + 1
        video_sources_cmd +=  f" + ( {work_dir}/chunks/{cur_idx}.ivf )"

        end_char=","
        if cur_idx == chunk_count - 1:
            end_char = ""

        append_cmd += f"{cur_idx}:0:{i}:0{end_char}" 

    # Build command json
    command_obj = [
        "--language",
        " 0:und",
        *video_sources_cmd.split(),
        *append_cmd.split(),
        *extra_commands
    ]

    # Serialize the command into JSON and write to file
    with open(f"{work_dir}/merge.json", 'w') as f:
        json.dump(command_obj, f, indent=4)

    run(f"mkvmerge @{work_dir}/merge.json --output {out_path}", shell=True, check=True)

# This doesn't work yet i believe
def add_xml_tag(name, value):
    return f"""    <Simple>
      <Name>{name}</Name>
      <String>{value}</String>
    </Simple>
"""

def set_mux_application(file, application_name):
    run(['mkvpropedit', file, '--set', f'writing-application={application_name}', '--set', f'muxing-application={application_name}'])

def extract_subs_and_chapters(in_path, out_path):
    run(['mkvmerge', '--output', out_path, '--no-audio', '--no-video', '(', in_path, ')', '--track-order', '0:4,0:3'])

def apply_audio_settings(file, encoder, encode_params):
    xml = f"""<?xml version="1.0"?>
<!-- <!DOCTYPE Tags SYSTEM "matroskatags.dtd"> -->
<Tags>
  <Tag>
    <Simple>
      <Name></Name>
      <String></String>
    </Simple>
  </Tag>
  <Tag>
    <Targets />
    <Simple>
      <Name>ENCODER</Name>
      <String>{encoder}</String>
    </Simple>
    <Simple>
      <Name>ENCODER_SETTINGS</Name>
      <String>{encode_params}</String>
    </Simple>
  </Tag>
</Tags>
"""
    xml_file = "audiosettings.xml"
    with open(xml_file, 'w') as f:
        f.write(xml)
    # Apply the settings using mkvpropedit
    run(['mkvpropedit', file, '--tags', f'track:a1:{xml_file}'])

# This function is mainly used to add the encoder parameters to the AV1 video stream
def apply_video_settings(file, encoder, encode_params, encoder_name):
    xml = f"""<?xml version="1.0"?>
<!-- <!DOCTYPE Tags SYSTEM "matroskatags.dtd"> -->
<Tags>
  <Tag>
    <Simple>
      <Name></Name>
      <String></String>
    </Simple>
  </Tag>
  <Tag>
    <Targets />
    <Simple>
      <Name>ENCODER</Name>
      <String>{encoder}</String>
    </Simple>
    <Simple>
      <Name>ENCODER_SETTINGS</Name>
      <String>{encode_params}</String>
    </Simple>
    <Simple>
      <Name>ENCODED_BY</Name>
      <String>{encoder_name}</String>
    </Simple>
  </Tag>
</Tags>
"""
    xml_file = "videosettings.xml"
    with open(xml_file, 'w') as f:
        f.write(xml)
    # Apply the settings using mkvpropedit
    run(['mkvpropedit', file, '--tags', f'track:v1:{xml_file}'])

def genFontCmd(ep_no):
    str = []
    for f in os.listdir(f"fonts/base"):
        ext = f [-3:] # TODO: bound to break with TTC
        str += [
            "--attachment-name", f"{f}", 
            "--attachment-mime-type", f"font/{ext}",
            "--attach-file", f"fonts/base/{f}"
        ]
    epFontDir = f"fonts/{ep_no}"
    if os.path.exists(epFontDir):
        for f in os.listdir(epFontDir):
            ext = f [-3:] # TODO: bound to break with TTC
            str += [
                "--attachment-name", f"{f}", 
                "--attachment-mime-type", f"font/{ext}",
                "--attach-file", f"{epFontDir}/{f}"
            ]

    return str 

def genInputCmd(file_in, track_name="", lang="und", is_default_track="yes"):
    return [
        "--language", f"0:{lang}",
        "--track-name", f"0:{track_name}",
        "--default-track-flag", f"0:{is_default_track}",
        "(", f"{file_in}",")", 
    ]

def genChapterCmd(chapter_in, lang="und"):
    return [
        "--chapter-language", f"{lang}",
        "--chapters", f"{chapter_in}",
    ]