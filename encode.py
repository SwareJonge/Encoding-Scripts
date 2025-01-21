import os
import fs
from subprocess import run
from mux import apply_video_settings, apply_audio_settings

# helper file with wrappers to encode with the usual encoders and apply the params to the output stream

encoder_name = "SwareJonge" # replace with your own name

def opusenc_get_version():
    res = run("opusenc --version", capture_output = True, text = True)
    line = res.stdout.splitlines()[0]
    splitlines = line.split()
    opus_tools_version = splitlines[2]
    libopus_version = splitlines[5][:-1]
    writing_application =  f'opusenc from opus-tools {opus_tools_version} using libopus {libopus_version}'
    return writing_application

def opusenc_encode(in_path: str, out_path: str, encoder_settings):
    tmp_out_path = out_path.replace(".mka", ".opus")
    if in_path.endswith(".wav") or in_path.endswith(".flac"):
        run(f"opusenc \"{in_path}\" \"{tmp_out_path}\" {encoder_settings}")
    else:
        # this should also use run(), but that requires some edits
        os.system(f"ffmpeg -i \"{in_path}\" -c:a flac -f flac - | opusenc - \"{tmp_out_path}\" {encoder_settings}")
    
    run(f"mkvmerge --output \"{out_path}\" ( \"{tmp_out_path}\" )")
    fs.remove_file(tmp_out_path)
    apply_audio_settings(out_path, opusenc_get_version(), encoder_settings)
    
def svt_get_binary_version():
    res = run("SvtAv1EncApp --version", capture_output = True, text = True)
    return res.stdout.splitlines()[0]

def svt_av1_encode(in_path: str, out_path: str, encoder_settings, worker_count, thread_affinity=2, scene_path :str = None, additional_flags=None):
    run(f"av1an -i \"{in_path}\" -o \"{out_path}\" -w {worker_count} --set-thread-affinity {thread_affinity} {additional_flags} --scenes \"{scene_path}\" -e svt-av1 -c mkvmerge -v \"{encoder_settings}\"")
    apply_video_settings(out_path, svt_get_binary_version(), encoder_settings, encoder_name)