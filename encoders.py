import os
import platform
import fs
import re

from subprocess import run
from mux import apply_video_settings, apply_audio_settings, apply_video_info_x265
from scenes import generate_scenes
from vstools import core

# helper file with wrappers to encode with the usual encoders and apply the params to the output stream

encoder_name = "SwareJonge" # replace with your own name

def aom_get_binary_version():
    res =run([
        "aomenc", "--help"
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=platform.system() == "Windows"
    )
    lines = res.stdout.splitlines()

    # Regex pattern to extract the desired part
    for line in lines:
        match = re.search(r"-\s+(AOMedia Project AV1 Encoder(?: Psy101)? [\d\.]+-[\w\d-]+)", line)
        if (match):
            return match.group(1)
    print(r"couldn't find AOM encoder version")
    exit(0)

def svt_get_binary_version():
    res = run([
            "SvtAv1EncApp", "--version"
        ], 
        capture_output=True,
        text=True,
        shell=platform.system() == "Windows"
    )
    ver = res.stdout.splitlines()[0]
    return re.sub(r"\s*\(release\)", "", ver)

def opusenc_get_version():
    res = run([
        "opusenc", "--version"
        ], 
        capture_output=True,
        text = True, 
        shell=platform.system() == "Windows"
    )
    line = res.stdout.splitlines()[0]
    splitlines = line.split()
    opus_tools_version = splitlines[2]
    libopus_version = splitlines[5][:-1]
    writing_application =  f'opusenc from opus-tools {opus_tools_version} using libopus {libopus_version}'
    return writing_application

def opusenc_encode(in_path: str, out_path: str, opusenc_settings):
    """Encode an audio file that is natively supported by opusenc"""
    tmp_out_path = out_path.replace(".mka", ".opus")
    run([
        "opusenc",
        in_path,
        tmp_out_path, 
        opusenc_settings
    ])
    run([
        "mkvmerge", 
        "--output", out_path,
        '(', tmp_out_path, ')'
    ])
    fs.remove_file(tmp_out_path)
    apply_audio_settings(out_path, opusenc_get_version(), opusenc_settings)

def opusenc_ffmpeg_encode(in_path: str, out_path: str, opusenc_settings:str, stream_no: int=0, ffmpeg_codec: str="copy", ffmpeg_format: str="wav", ffmpeg_seek_settings: str=""):
    """Encode an audio file with opusenc with help from ffmpeg"""
    tmp_out_path = out_path.replace(".mka", ".opus")
    # this should also use run(), but that requires some edits
    os.system(f"ffmpeg {ffmpeg_seek_settings} -i \"{in_path}\" -map 0:a:{stream_no} -c:a {ffmpeg_codec} -f {ffmpeg_format} - | opusenc - \"{tmp_out_path}\" {opusenc_settings}")
    run([
        "mkvmerge", 
        "--output", out_path,
        '(', tmp_out_path, ')'
    ])
    fs.remove_file(tmp_out_path)
    apply_audio_settings(out_path, opusenc_get_version(), opusenc_settings)

def svt_av1_encode_standalone(in_path: str, out_path: str, encoder_settings, extra_encoder_settings:str =""):
    """Encode a vapoursynth script with vspipe and SVT-AV1"""
    os.system(f"vspipe \"{in_path}\" -c y4m - | SvtAv1EncApp -i - -b \"{out_path}.ivf\" {extra_encoder_settings} {encoder_settings}")
    run([
        "mkvmerge",
        "--output", out_path,
        '(', f"{out_path}.ivf", ')'
    ])
    apply_video_settings(out_path, svt_get_binary_version(), encoder_settings, encoder_name)

# Deprecated by av1_encode
def svt_av1_encode(in_path: str, out_path: str, encoder_settings: str, worker_count: int=0, thread_affinity: int=0, scene_path :str= "", extra_av1an_flags: list[str]=None):
    """Encode a file(can be either a vapoursynth script or a video file) with av1an and SVT-AV1"""
    run([
        "av1an",
        "-i", in_path,
        "-o", out_path,
        "--scenes", scene_path, 
        "-w", str(worker_count),
        "--set-thread-affinity", str(thread_affinity),
        "-c", "mkvmerge",
        "-e", "svt-av1",         
        "-v", encoder_settings,
        *extra_av1an_flags
    ])
    apply_video_settings(out_path, svt_get_binary_version(), encoder_settings, encoder_name)

def av1_encode(in_path: str, out_path: str, encoder: str, encoder_settings: str, worker_count: int=0, thread_affinity: int=0, scene_path :str="", extra_av1an_flags: list[str]=None):
    """Encode a file(can be either a vapoursynth script or a video file) with av1an and an AV1 encoder, either aomenc or SVT-AV1(sorry rav1e)"""
    ver = svt_get_binary_version() if encoder == "svt-av1" else aom_get_binary_version()
    print(f"Encoding using {ver}")
    run([
        "av1an",
        "-i", in_path,
        "-o", out_path,
        "--scenes", scene_path, 
        "-w", str(worker_count),
        "--set-thread-affinity", str(thread_affinity),
        "-c", "mkvmerge",
        "-e", encoder,         
        "-v", encoder_settings,
        *extra_av1an_flags
    ])
    apply_video_settings(out_path, ver, encoder_settings, encoder_name)

def x265_encode(in_path: str, out_path: str, settings: str, scene_path: str, worker_count: int=0, thread_affinity: int=0, extra_av1an_flags: list[str]=None):
    """Encode a file(can be either a vapoursynth script or a video file) with av1an and x265"""
    run(["av1an",
        "-i", in_path,
        "-o", out_path,
        "--scenes", scene_path,
        "-w", str(worker_count), 
        "--set-thread-affinity", str(thread_affinity),
        "-c", "mkvmerge",
        "-e", "x265",
        "-v", settings,
        *extra_av1an_flags
    ])
    apply_video_info_x265(out_path, encoder_name)

# example usage
def luma_boost_encode(in_path: str, out_path: str, zones_path : str, scene_path: str, encoder_settings: str):
    if not os.path.exists(scene_path):
        src = core.bs.VideoSource(in_path)
        generate_scenes(src, zones_path, "scenechanges.pickle", scene_path, encoder_settings)
    svt_av1_encode(in_path, out_path, encoder_settings, 8, 2, scene_path, ["--keep", "--resume"])