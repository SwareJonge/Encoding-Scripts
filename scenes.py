from vapoursynth import VideoNode
from vstools import  Keyframes, clip_async_render
import math
import statistics
import pickle

import os
import json
import math

class ZoneOverride: 
    def __init__(self, encoder, passes, video_params, min_scene_len):
        self.encoder=encoder
        self.passes=passes
        self.video_params=video_params
        self.min_scene_len=min_scene_len
        # TODO: misses photon noise and extra_splits_len(does this one matter? this gets handled by the scene detect function)

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
    
class KeyFrameData:
    def __init__(self, start_frame, end_frame, zone_overrides : ZoneOverride):
        self.start_frame = start_frame
        self.end_frame = end_frame
        self.zone_overrides = zone_overrides
    
    def __repr__(self):
        return f"KeyFrameData({self.start_frame}, {self.end_frame}, {self.zone_overrides})"


    def to_dict(self):
        """Convert the KeyFrameData object to a dictionary."""
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "zone_overrides": self.zone_overrides.to_dict() if self.zone_overrides else None
        }

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
    factor = brig_geom - 1 # "invert" brightness
    luma_bias = abs(factor * 100) # scale to percentages and make it a positive value again

    return luma_bias

def get_scenechages(clip: VideoNode, out_path: str = None) -> list[int]:
    conifg_path = f"{out_path}"
    if not os.path.exists(conifg_path):
        scenechanges = Keyframes.from_clip(clip, 0)
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


def generate_scenes(src: VideoNode, zones_path: str, scenechange_path: str, out_path: str, encode_settings: str, luma_bias=True):
    if luma_bias:
        kfs: list[KeyFrameData] = generate_keyframes_luma_boost_av1(src, zones_path, scenechange_path, encode_settings)
    else:
        kfs: list[KeyFrameData] = generate_keyframes(src, zones_path, scenechange_path, encode_settings)
    # Convert each KeyFrameData to a dictionary and dump to JSON
    kf_dicts = { "scenes": [kf.to_dict() for kf in kfs], "frames": src.num_frames }
    json_out = json.dumps(kf_dicts)

    # Write to file
    with open(out_path, 'w') as f:
        f.write(json_out)
