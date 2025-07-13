import json
import os
import subprocess
from collections import Counter
from vapoursynth import core

import encoders
import fs
import ivftools
import mux
from scenes import KeyFrameData, ZoneOverride, kf_to_json, generate_scenes, scene_minimum_boost

def get_size_str(size):
    if size < 1024:
        return f"{size} bytes"
    elif size < pow(1024,2):
        return f"{round(size/1024, 2)} KB"
    elif size < pow(1024,3):
        return f"{round(size/(pow(1024,2)), 2)} MB"
    elif size < pow(1024,4):
        return f"{round(size/(pow(1024,3)), 2)} GB"

def find_optimal_levels(src_path, script_path, scene_out_path, scenechange_path, enc_params, base_crf, preset, fast_preset, color_info, luma_bias, minimum_boost_params, minimum_boost_out_name, min_hierarch = 3, use_fast_video=False, video_out_path="test/optimized.mkv"):
    """
    Encodes video with options for luma bias and mimimum boost
    minimum boost params are stored in a json file, formatted like this:
    "minimum_boost_params": {
        "worst_crf": 23,
        "best_crf": 12,
        "crf_step": 1,
        "bitrate_cap": 40000,
        "min_ssimu2_score": 87.5
    },
    hierarchical levels go from 2 to 5 for SVT-AV1, where i've found that 3 is in most cases more efficent than the other levels
    4 is the default for good presets
    5 is the default for very fast presets
    2 generally isn't more efficient, just don't use it
    returns a string with the encoder params for use with av1an, or SVT-AV1
    """
    src = core.bs.VideoSource(src_path)
    fs.create_dir(f"test/")
    fs.create_dir(f"test/hierarch")
    fs.create_dir(f"autoboost")
    fs.create_dir(f"lumaboost")
    scenes = generate_scenes(src, "", scenechange_path, f"test/scenes.json", "", False, False)
    num_scenes = len(scenes)
    # Generate the custom scenes
    if luma_bias:
        luma_boost_out_name = script_path[:-4]
        luma_boost_out_path = f"lumaboost/{luma_boost_out_name}.json"
        if not os.path.exists(luma_boost_out_path):
            modded_scenes = generate_scenes(src, "", scenechange_path, luma_boost_out_path, f"--preset {fast_preset} --lp 2 --crf {base_crf} {enc_params} {color_info}", luma_bias=luma_bias)
        else:
            scenes_dict = json.load(open(luma_boost_out_path, "r", encoding="utf-8"))["scenes"]
            modded_scenes = [ KeyFrameData(**cur_modded_scene) for cur_modded_scene in scenes_dict ]
    else:
        modded_scenes = scenes

    if minimum_boost_params is not None:
        # Run minimum boost
        autoboost_scene_path = f"autoboost/{minimum_boost_out_name}.json"
        if not os.path.exists(autoboost_scene_path):
            print(minimum_boost_params)
            
            with open(f"autoboost/{minimum_boost_out_name}.log", "w+") as f:
                for i, modded_scene in enumerate(modded_scenes):                    
                    scene_minimum_boost(src[modded_scene.start_frame:modded_scene.end_frame], modded_scenes[i], minimum_boost_params["best_crf"], minimum_boost_params["worst_crf"], minimum_boost_params["crf_step"], minimum_boost_params["min_ssimu2_score"], minimum_boost_params["bitrate_cap"], enc_params, fast_preset, color_info, f)
            kf_to_json(modded_scenes, autoboost_scene_path, src.num_frames)

        else:
            scenes_dict = json.load(open(autoboost_scene_path, "r", encoding="utf-8"))["scenes"]
            modded_scenes = [ KeyFrameData(**cur_modded_scene) for cur_modded_scene in scenes_dict]
            print(f"Loaded autoboost scenes")
            #print(modded_scenes)

    for h in range(min_hierarch, 6):
        video_path = f"test/{h}.mkv"
        if not os.path.exists(video_path):
            fast_pass_settings = f"--preset {fast_preset} --lp 2 --crf {base_crf} {enc_params} --hierarchical-levels {h} {color_info}"
            scene_path = f"test/scenes_h{h}.json"
            if not os.path.exists(scene_path):
                for i, modded_scene in enumerate(modded_scenes):
                    if modded_scene.zone_overrides is not None:
                        modded_scenes[i].zone_overrides.update_video_params("--hierarchical-levels", h)
                kf_to_json(modded_scenes, scene_path, src.num_frames)
            encoders.svt_av1_encode(script_path, video_path, fast_pass_settings, 15, 2, scene_path, ["--keep", "--temp", f"test/hierarch/{h}"])

    processed_scenes = [
        json.load(open(f"test/scenes_h{h}.json", "r", encoding="utf-8"))["scenes"] for h in range(min_hierarch, 6)
    ]

    hierarch_counter = Counter()
    estimated_out_size = 0
    concat_list = []
    kfs = []
    best_hierarchs = []
    for sceneNo in range(num_scenes):
        lowest_size = 0
        best_hierarch = 5
        wrote_hierarch = False
        
        for h in range(min_hierarch, 6):
            ivf_path = f"./test/hierarch/{h}/encode/{sceneNo:00005}.ivf"
            test_section_size = os.path.getsize(ivf_path)
            if lowest_size == 0 or test_section_size < lowest_size:
                lowest_size = test_section_size
                best_hierarch = h
                wrote_hierarch = True

        if not wrote_hierarch:
            print(f"ERROR scene {sceneNo}") # This should never happen
        
        estimated_out_size += lowest_size
        hierarch_counter[best_hierarch] += 1
        best_hierarchs += [best_hierarch]
        
        if use_fast_video:
            concat_list += [f"./test/hierarch/{best_hierarch}/encode/{sceneNo:00005}.ivf"]

    most_common_hierarch, count = hierarch_counter.most_common(1)[0]
    default_enc_params = f"--crf {base_crf} {enc_params} --hierarchical-levels {most_common_hierarch}"

    for sceneNo in range(num_scenes):
        best_hierarch = best_hierarchs[sceneNo]
        sceneoverride_dict = processed_scenes[best_hierarch-min_hierarch][sceneNo]
        sceneoverride = KeyFrameData(**sceneoverride_dict)

        if sceneoverride.zone_overrides is not None: # this means it's a luma biased scene or a zone, or a modfied crf zone
            sceneoverride.zone_overrides.replace_video_param("--preset", preset)
        elif best_hierarch != most_common_hierarch:
            sceneoverride.zone_overrides = ZoneOverride("svt_av1", 1, f"--preset {preset} --lp 2 --crf {base_crf} {enc_params} --hierarchical-levels {best_hierarch} {color_info}", 24)
            
        kfs.append(sceneoverride)

    kf_to_json(kfs, scene_out_path, src.num_frames)    

    print(f"Fast Pass output size: {get_size_str(estimated_out_size)}")

    if use_fast_video:
        merge_path = f"test/optimized.ivf"
        if not os.path.exists(merge_path):
            ivftools.merge_chunks(merge_path, concat_list, 1920, 1080, 24000, 1001)
        subprocess.run([
            "mkvmerge",
            "--output", video_out_path,
            "(", merge_path, ")"
        ])
        mux.apply_video_settings(video_out_path, encoders.svt_get_binary_version(), f"--preset {preset} --lp 2 {enc_params} --hierarchical-levels {best_hierarch} {color_info}--preset {preset} --lp 2 {enc_params} --hierarchical-levels {most_common_hierarch} {color_info}", "SwareJonge")

    fs.remove_dir("test/")
    return default_enc_params