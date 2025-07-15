from vapoursynth import core, VideoNode
from vstools import  Keyframes, clip_async_render
import json
import math
import pickle
import os
import numpy
import math
import statistics
import subprocess
import tqdm

import ivftools

class ZoneOverride: 
    def __init__(self, encoder, passes, video_params: list[str], min_scene_len, photon_noise=0, extra_splits_len=0):
        self.encoder=encoder
        self.passes=passes
        if isinstance(video_params, str):
            self.video_params = video_params.split(" ")
        else:
            self.video_params=video_params
        self.min_scene_len=min_scene_len
        self.min_scene_len=min_scene_len
        # TODO: misses photon noise and extra_splits_len(does this one matter? this gets handled by the scene detect function)
        # currently discarding it, because i don't need it
    def __repr__(self):
        return f"ZoneOverride({self.encoder}, {self.passes}, {self.video_params}, {self.min_scene_len})"
    
    def to_dict(self):
        """Convert the ZoneOverride object to a dictionary."""
        return {
            "encoder": self.encoder,
            "passes": self.passes,
            "video_params": self.video_params,
            "min_scene_len": self.min_scene_len
        }

    def replace_video_param(self, param_name, param_value): 
        param_idx = self.video_params.index(param_name) + 1
        self.video_params[param_idx] = f"{param_value}"

    def update_video_params(self, param_name, param_value):
        if param_name in self.video_params: # eh, i feel like this sometimes won't work
            param_idx = self.video_params.index(param_name) + 1
            self.video_params[param_idx] = f"{param_value}"
        else:
            self.video_params += [param_name, f"{param_value}"]
    
class KeyFrameData:
    def __init__(self, start_frame, end_frame, zone_overrides):
        self.start_frame = start_frame
        self.end_frame = end_frame
        if isinstance(zone_overrides, ZoneOverride) or zone_overrides is None:
            self.zone_overrides = zone_overrides
        else:
            self.zone_overrides = ZoneOverride(**zone_overrides)
            
    def __repr__(self):
        return f"KeyFrameData({self.start_frame}, {self.end_frame}, {self.zone_overrides})"


    def to_dict(self):
        """Convert the KeyFrameData object to a dictionary."""
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "zone_overrides": self.zone_overrides.to_dict() if self.zone_overrides else None
        }

# TODO: rewrite this and put it in a class
def scene_minimum_boost(src: VideoNode, scene_out: KeyFrameData, best_crf, worst_crf, crf_step, min_score, bitrate_cap, enc_params, fast_preset, color_info, f):
    """
    Increases CRF for a scene
    Currently SVT-AV1 only
    """
    params = f"--preset {fast_preset} --lp 6 --crf {worst_crf} {enc_params} {color_info}"
    for crf in range(worst_crf, best_crf - 1, -crf_step):
        params = f"--preset {fast_preset} --lp 6 --crf {crf} {enc_params} {color_info}"
        out_name = f"C:/temp/{scene_out.start_frame}_{scene_out.end_frame}crf{crf}.ivf"
        avg_score = 0
        scene_lowest_score = 100
        with subprocess.Popen([
            "SvtAv1EncApp",
            "-i", "-",
            "-b", out_name,
            "--progress", "3",
            "--keyint", "-1",
            "--hierarchical-levels", "5", # This speeds up the encoding as well
            *params.split(" ")
        ], stdin=subprocess.PIPE) as process: 
            src.output(process.stdin, y4m=True)
            process.communicate()
        
            section_bitrate = ivftools.IVFFile(out_name).get_bitrate()
            frames = src.vszip.SSIMULACRA2(core.bs.VideoSource(out_name)).frames()
            
            score_array = numpy.array([frame.props['SSIMULACRA2'] for frame in frames])

            scene_lowest_score = numpy.min(score_array)
            avg_score = numpy.mean(score_array)

            print(f"Avg Score: {avg_score:.2f} Worst: {scene_lowest_score:.2f}")

            if numpy.all(score_array >= min_score):
                print("No bad frames")
                break
            
            if section_bitrate > bitrate_cap:
                print("Bitrate cap hit")
                #f.write(f"Bitrate cap hit\n")
                break
    
    if worst_crf != crf:
        f.write(f"{scene_out.start_frame}_{scene_out.end_frame} CRF has been updated to {crf} Bitrate is {section_bitrate} kbps Scene Avg_Score: {avg_score} Scene Lowest Score: {scene_lowest_score}\n")
        if scene_out.zone_overrides is not None:
            scene_out.zone_overrides.replace_video_param("--crf", crf)
        else:
            scene_out.zone_overrides = ZoneOverride("svt_av1", 1, params, 24)
    
def minimum_boost(src: VideoNode, scenes: list[KeyFrameData], log_path: str, minimum_boost_params, base_crf, fast_preset, enc_params, keyframe_file, color_info):
    """
    Boost CRF of a scene and save the results in the KeyFrameData list
    SVT-AV1 only(wouldn't be the case if i were smarter)
    """
    WORST_CRF = minimum_boost_params["worst_crf"]
    MIN_SCORE_THRES = minimum_boost_params["min_ssimu2_score"]
    BITRATE_CAP = minimum_boost_params["bitrate_cap"]
    MAX_BITRATE = BITRATE_CAP + (BITRATE_CAP / 10)
    params = f"--preset {fast_preset} --lp 6 --crf {base_crf} {enc_params} {color_info}"
    print(params)
    if not os.path.exists("autoboost/fastpass.ivf"):
        with subprocess.Popen([
            "SvtAv1EncApp",
            "-i", "-",
            "-b", "autoboost/fastpass.ivf",
            "--progress", "3",
            "--config", keyframe_file,
            *params.split(" ")
        ], stdin=subprocess.PIPE) as process: 
            src.output(process.stdin, y4m=True)
            process.communicate()

    enc_ivf = ivftools.IVFFile("autoboost/fastpass.ivf")
    enc_src = core.bs.VideoSource("autoboost/fastpass.ivf")
    print("Computing SSIMU2 of fast pass encode")
    enc_frames = src.vszip.SSIMULACRA2(enc_src).frames()
    
    score_list = numpy.array([f.props['SSIMULACRA2'] for f in tqdm(enc_frames)])

    print("Computed SSIMU2 of fast pass encode")
    with open(log_path, "w+") as f:
        for i, modded_scene in enumerate(scenes):
            if enc_ivf.get_section_bitrate(modded_scene.start_frame, modded_scene.end_frame) > MAX_BITRATE:
                continue
            
            scene_scores = score_list[modded_scene.start_frame:modded_scene.end_frame]
            if numpy.any(scene_scores < MIN_SCORE_THRES):
                print(f"Boosting scene {modded_scene.start_frame}_{modded_scene.end_frame}")
                scene_minimum_boost(src[modded_scene.start_frame:modded_scene.end_frame], scenes[i], minimum_boost_params["best_crf"], WORST_CRF - 1, minimum_boost_params["crf_step"], MIN_SCORE_THRES, MAX_BITRATE, enc_params, fast_preset, color_info, f)
                

# Merging zones parsing with keyframe generation
def parse_zones(zones_path: str) -> list[KeyFrameData]:
    zones = []

    if not os.path.exists(zones_path):
        return None
    
    # Read zones and create ranges
    with open(zones_path, 'r') as f:
        for line in f:
            l = line.split()
            start_frame = int(l[0])
            end_frame = int(l[1])
            encoder = l[2] if l[2] != "svt-av1" else "svt_av1" # stupid fixup
            enc_params = l[4:]
            zones.append(KeyFrameData(start_frame, end_frame, ZoneOverride(encoder, 1, enc_params, 24)))
    
    return zones

def finish_scene(keyframes: list[KeyFrameData], override: ZoneOverride, start_frame, end_frame, scene_len):
    extra_kfs = 0
    extra_splits = 0
    if scene_len > 240:  # make extra splits if scene is longer than 10 seconds
        extra_splits = math.floor(scene_len / 240)
        rem = scene_len % 240
        for idx in range(extra_splits):
            keyframes.append(KeyFrameData(start_frame + (idx * 240), start_frame + ((idx + 1) * 240), override))
            extra_kfs += 1
            extra_splits += 1                    
        # If remainder is less than 120 frames, merge it with the last chunk, otherwise add a new chunk
        if rem < 120:
            keyframes[len(keyframes)-1].end_frame = end_frame
        else:
            keyframes.append(KeyFrameData(keyframes[len(keyframes)-1].end_frame, end_frame, override))
            extra_kfs += 1
            extra_splits += 1
    else:
        # Append the keyframe data for this section
        keyframes.append(KeyFrameData(start_frame, end_frame, override))
        extra_kfs += 1 

    return [extra_kfs, extra_splits]

def get_darkness(video, start, end):
    brightness = []
    ref = video[start:end].std.PlaneStats(plane=0)

    render = clip_async_render(
            ref, outfile=None, progress=f"Getting frame props... from {start} to {end}",
            callback=lambda _, f: f.props.copy()
    )
    props = [prop["PlaneStatsAverage"] for prop in render]

    for prop in props:
                brightness.append(prop)

    brig_geom = round(statistics.geometric_mean([x+0.01 for x in brightness]), 2) #x+1
    factor = 1 - brig_geom # "invert" brightness
    luma_bias = factor * 100 # scale to percentages and make it a positive value again

    return luma_bias

def get_scenechages(clip: VideoNode, out_path: str = None) -> list[int]:
    conifg_path = f"{out_path}"
    if not os.path.exists(conifg_path):
        scenechanges = Keyframes.from_clip(clip, 2)
        with open(conifg_path, "wb") as f:
            pickle.dump(scenechanges, f)
    
    with open(conifg_path, "rb") as f:
        scenechanges = pickle.load(f)

    return scenechanges

def add_luma_boost_scene(clip: VideoNode, frames: list[KeyFrameData], override: ZoneOverride, scene_start, scene_end, scene_len, default_encoder_settings: str):
    if override is not None and override.encoder == "aom":
        override.passes = 2
    
    dr = get_darkness(clip, scene_start, scene_end)
    if dr > 30:
        luma_boost = math.ceil(dr * 1.2) # multiply darkness of scene by 1.2, this will be the luma bias
        clamped = min(luma_boost, 100) # clamp value to 100
        luma_param = f"--frame-luma-bias {clamped}"
        if override is None:
            params = f"{default_encoder_settings} {luma_param}"
            override = ZoneOverride("svt_av1", 1, params.split(' '), 24)
            
        else:
            if override.encoder == "aom":
                aom_val = round(clamped / (100/15))
                luma_param = f"--luma-bias={aom_val}"
                aomOverride = ZoneOverride(override.encoder, 2, override.video_params, 24)
                if not any(arg.startswith("--luma-bias") for arg in override.video_params): # let user manually set frame luma bias if desired
                    aomOverride.video_params += luma_param.split(' ')
                    return finish_scene(frames, aomOverride, scene_start, scene_end, scene_len)
            elif "--frame-luma-bias" not in override.video_params: # let user manually set frame luma bias if desired
                svtOverride = ZoneOverride(override.encoder, override.passes, override.video_params, 24)
                svtOverride.video_params += luma_param.split(' ')
                return finish_scene(frames, svtOverride, scene_start, scene_end, scene_len)
    return finish_scene(frames, override, scene_start, scene_end, scene_len)

def add_luma_boost_scene_aom(clip: VideoNode, frames: list[KeyFrameData], override: ZoneOverride, scene_start, scene_end, scene_len, default_encoder_settings: str):
    dr = get_darkness(clip, scene_start, scene_end)
    if dr > 30:
        luma_boost = math.ceil(dr * 1.2) # multiply darkness of scene by 1.2, this will be the luma bias
        clamped = min(luma_boost, 100) # clamp value to 100
        aom_val = round(clamped / (100/15))
        luma_param = f"--luma-bias={aom_val}"
        if override is None:
            params = f"{default_encoder_settings} {luma_param}"
            override = ZoneOverride("aom", 2, params.split(' '), 24)
        else:
            if "--luma-bias" not in override.video_params: # let user manually set frame luma bias if desired
                override.video_params += luma_param.split()
    return finish_scene(frames, override, scene_start, scene_end, scene_len)

# Keyframe generation with zone handling
def generate_keyframes_luma_boost_av1(clip: VideoNode, zones_path: str, scenechange_path: str, default_encoder_settings: str) -> list[KeyFrameData]:
    end_frame = clip.num_frames
    zones = parse_zones(zones_path)
    zonecount = len(zones) if zones is not None else 0
    scenechanges = get_scenechages(clip, scenechange_path)

    scene_start = 0  # start of the scene
    key_no = 0
    zoneIdx = 0    
    num_extra_splits = 0
    override: ZoneOverride = None
    frames = []
    for i in range(end_frame):  # Iterate over all frames and detect scene changes
        scene_len = i - scene_start
        if zoneIdx < zonecount: # zones take priority over normal scenechanges, however splits are still made if a scenechange is found in that zone
            if zones[zoneIdx].start_frame == i: # always make a split at a zone start
                if i != 0: # if it's a zone that starts on frame 0, don't finish the split(since that's not possible)
                    increments = add_luma_boost_scene(clip, frames, override, scene_start, i, scene_len, default_encoder_settings)
                    key_no += increments[0]
                    num_extra_splits += increments[1]
                override = zones[zoneIdx].zone_overrides
                scene_start = i                
                continue
            if zones[zoneIdx].end_frame == i: # finish zone and reset all flags
                increments = add_luma_boost_scene(clip, frames, override, scene_start, i, scene_len, default_encoder_settings)
                key_no += increments[0]
                num_extra_splits += increments[1]

                override = None
                zoneIdx += 1
                
                if zoneIdx < zonecount: # Edge case check for when end frame of previous zone is the same as the start frame of the current zone
                    if zones[zoneIdx].start_frame == i:
                        override = zones[zoneIdx].zone_overrides
                scene_start = i
                continue

        if i in scenechanges:
            if scene_len > 24: # only split if scene is longer than 24 frames                
                increments = add_luma_boost_scene(clip, frames, override, scene_start, i, scene_len, default_encoder_settings)
                key_no += increments[0]
                num_extra_splits += increments[1]
                scene_start = i  # start of the next scene


    last_scene_duration = end_frame - scene_start
    increments = add_luma_boost_scene(clip, frames, override, scene_start, end_frame, last_scene_duration, default_encoder_settings)
    key_no += increments[0]
    num_extra_splits += increments[1]

    print(f"\nFound {key_no} Scenes with {num_extra_splits} extra splits.")
    return frames

# Keyframe generation with zone handling
def generate_keyframes(clip: VideoNode, zones_path: str, scenechange_path: str, default_encoder_settings: str) -> list[KeyFrameData]:
    end_frame = clip.num_frames
    zones = parse_zones(zones_path)
    zonecount = len(zones) if zones is not None else 0
    scenechanges = get_scenechages(clip, scenechange_path)

    scene_start = 0  # start of the scene
    key_no = 0
    zoneIdx = 0    
    num_extra_splits = 0
    override: ZoneOverride = None
    frames = []
    for i in range(end_frame):  # Iterate over all frames and detect scene changes
        scene_len = i - scene_start
        if zoneIdx < zonecount: # zones take priority over normal scenechanges, however splits are still made if a scenechange is found in that zone
            if zones[zoneIdx].start_frame == i: # always make a split at a zone start
                if i != 0: # if it's a zone that starts on frame 0, don't finish the split(since that's not possible)
                    increments = finish_scene(frames, override, scene_start, i, scene_len)
                    key_no += increments[0]
                    num_extra_splits += increments[1]
                override = zones[zoneIdx].zone_overrides
                scene_start = i                
                continue
            if zones[zoneIdx].end_frame == i: # finish zone and reset all flags
                increments = finish_scene(frames, override, scene_start, i, scene_len)
                key_no += increments[0]
                num_extra_splits += increments[1]

                override = None
                zoneIdx += 1
                
                if zoneIdx < zonecount: # Edge case check for when end frame of previous zone is the same as the start frame of the current zone
                    if zones[zoneIdx].start_frame == i:
                        override = zones[zoneIdx].zone_overrides
                scene_start = i
                continue

        if i in scenechanges:
            if scene_len > 24: # only split if scene is longer than 24 frames                
                increments = finish_scene(frames, override, scene_start, i, scene_len)
                key_no += increments[0]
                num_extra_splits += increments[1]
                scene_start = i  # start of the next scene


    last_scene_duration = end_frame - scene_start
    increments = finish_scene(frames, override, scene_start, end_frame, last_scene_duration)
    key_no += increments[0]
    num_extra_splits += increments[1]

    print(f"\nFound {key_no} Scenes with {num_extra_splits} extra splits.")
    return frames

def kf_to_json(kf_list: list[KeyFrameData], out_path, num_frames):
    # Convert each KeyFrameData to a dictionary and dump to JSON
    kf_dicts = { "scenes": [kf.to_dict() for kf in kf_list], "frames": num_frames }
    json_out = json.dumps(kf_dicts)
    with open(out_path, 'w') as f:
        f.write(json_out)

def generate_scenes(src: VideoNode, zones_path: str, scenechange_path: str, out_path: str, encode_settings: str, luma_bias=True, write_to_file=True):
    if luma_bias:
        kfs: list[KeyFrameData] = generate_keyframes_luma_boost_av1(src, zones_path, scenechange_path, encode_settings)
    else:
        kfs: list[KeyFrameData] = generate_keyframes(src, zones_path, scenechange_path, encode_settings)

    if write_to_file:
        kf_to_json(kfs, out_path, src.num_frames)
    return kfs