import json
import os
import time
from subprocess import CalledProcessError, run

# I'm way too lazy to add actual xml writing, so just do it the jank way

def add_xml_tag(name, value):
    return f"""<Simple>
      <Name>{name}</Name>
      <String>{value}</String>
    </Simple>
"""

def set_mux_application(file, application_name):
    run([
        "mkvpropedit", 
        file, 
        "--set", f"writing-application={application_name}", 
        "--set", f"muxing-application={application_name}"
    ])

def extract_subs_and_chapters(in_path, out_path):
    run([
        "mkvmerge", 
        "--output", out_path, 
        "--no-audio", 
        "--no-video", 
        "(", in_path, ")"
    ])

def get_encoded_date():
    # Get the current time in ISO 8601 format (UTC)
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

def apply_audio_settings(file, encoder, encode_params):
    """Function to write info about the encoder to file, using standardized tags, mainly used with opusenc"""
    date = get_encoded_date()
    xml = f"""<?xml version="1.0"?>
<!-- <!DOCTYPE Tags SYSTEM "matroskatags.dtd"> -->
<Tags>
  <Tag>
    <Targets />
    <Simple>
      <Name>DATE_ENCODED</Name>
      <String>{date}</String>
    </Simple>
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
    run([
        "mkvpropedit", 
        file, 
        "--tags", f"track:1:{xml_file}"
    ])

def apply_video_settings(file, encoder, encode_params, encoder_name):
    """Function to write info about the encoder to file, mainly used for AV1"""
    date = get_encoded_date()
    xml = f"""<?xml version="1.0"?>
<!-- <!DOCTYPE Tags SYSTEM "matroskatags.dtd"> -->
<Tags>
  <Tag>
    <Targets />
    <Simple>
      <Name>DATE_ENCODED</Name>
      <String>{date}</String>
    </Simple>
    <Simple>
      <Name>ENCODED_BY</Name>
      <String>{encoder_name}</String>
    </Simple>
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
    xml_file = "settings.xml"
    with open(xml_file, 'w') as f:
        f.write(xml)
    # Apply the settings using mkvpropedit
    run([
        "mkvpropedit", 
        file, 
        "--tags", f"track:1:{xml_file}"
    ])

def apply_video_info_x265(file, encoder_name):
    """Function to write the date and name of who encoded the video to the video track"""
    date = get_encoded_date()
    xml = f"""<?xml version="1.0"?>
<!-- <!DOCTYPE Tags SYSTEM "matroskatags.dtd"> -->
<Tags>
  <Tag>
    <Targets />
    <Simple>
      <Name>DATE_ENCODED</Name>
      <String>{date}</String>
    </Simple>
    <Simple>
      <Name>ENCODED_BY</Name>
      <String>{encoder_name}</String>
    </Simple>
  </Tag>
</Tags>
"""
    xml_file = "settings.xml"
    with open(xml_file, 'w') as f:
        f.write(xml)
    # Apply the settings using mkvpropedit
    run([
        "mkvpropedit", 
         file, 
         "--tags", f"track:1:{xml_file}"
    ])

def genFontCmd(ep_no):
    str = []
    for f in os.listdir(f"fonts/base"):
        ext = f [-3:] # TODO: bound to break with TTC
        str += [
            "--attachment-name", f, 
            "--attachment-mime-type", f"font/{ext}",
            "--attach-file", f"fonts/base/{f}"
        ]
    epFontDir = f"fonts/{ep_no}"
    if os.path.exists(epFontDir):
        for f in os.listdir(epFontDir):
            ext = f [-3:] # TODO: bound to break with TTC
            str += [
                "--attachment-name", f, 
                "--attachment-mime-type", f"font/{ext}",
                "--attach-file", f"{epFontDir}/{f}"
            ]

    return str 

def genInputCmd(file_in, track_name="", lang="und", is_default_track="yes"):
    return [
        "--language", f"0:{lang}",
        "--track-name", f"0:{track_name}",
        "--default-track-flag", f"0:{is_default_track}",
        "(", file_in, ")", 
    ]

def genChapterCmd(chapter_in, lang="und"):
    return [
        "--chapter-language", lang,
        "--chapters", chapter_in,
    ]

# TODO: untested
def merge(out_path, video_in, audio_in, subs_in, fonts_in, chapter_in, overwrite_mux_application=False, mux_application_name="sj-auto-muxer-v0.1"):
    cmd = [
        *genInputCmd(**video_in),
        *[genInputCmd(**audio) for audio in audio_in],
        *[genInputCmd(**sub) for sub in subs_in],
        *fonts_in,
        # Chapters
        *genChapterCmd(chapter_in),
    ]

    # Serialize the command into JSON and write to file
    with open("merge.json", 'w') as f:
        json.dump(cmd, f, indent=4)
    
    # Execute the command
    try:
        run(["mkvmerge"
            "@merge.json",
            "--output",
            out_path,
            ],
            shell=True, 
            check=True
        )
        if overwrite_mux_application:
            set_mux_application(out_path, mux_application_name) # Maybe just leave this out and let the user decide in the base script
    except CalledProcessError as e:
        print(f"Error during merging: {e}")
    finally:
        os.remove("merge.json")