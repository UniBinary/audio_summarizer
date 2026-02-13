#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健壮的音频提取工具
功能：
1. 多进程并行提取音频
2. 自动检查已存在音频的正确性（时长匹配）
3. 不正确的音频自动重新提取
4. 支持命令行参数配置
"""

import json
import subprocess
import time
import sys
import argparse
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

class AudioExtractor:
    def __init__(self, ffmpeg_path, output_dir):
        self.ffmpeg_path = ffmpeg_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.total_duration = 0
    
    def get_duration(self, file_path):
        """获取媒体文件时长（秒）"""
        try:
            # 使用ffprobe获取时长
            ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
            if not ffprobe_path.exists():
                ffprobe_path = self.ffmpeg_path.with_name("ffprobe.exe")
            
            cmd = [
                str(ffprobe_path),
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(file_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0:
                return float(result.stdout.strip())
        except:
            pass
        return None
    
    def check_audio_correct(self, video_path, audio_path):
        """检查音频文件是否正确（时长匹配）"""
        if not audio_path.exists():
            return False
        
        # 获取视频和音频时长
        video_duration = self.get_duration(video_path)
        audio_duration = self.get_duration(audio_path)
        
        print(f"检查: {audio_path} | 视频时长: {video_duration} 秒 | 音频时长: {audio_duration} 秒")

        if video_duration is None or audio_duration is None:
            print("无法获取时长")
            return False  # 无法验证，假设不正确

        # 检查时长差异（允许5秒差异）
        duration_diff = abs(video_duration - audio_duration)
        return duration_diff <= 5
    
    def extract_audio(self, task):
        """提取单个音频文件"""
        idx, video_path = task
        audio_path = self.output_dir / f"{idx+1:03d}.mp3"  # 001.mp3 对应 videos[0]
        
        # 检查音频文件是否正确
        if audio_path.exists():
            audio_duration = self.get_duration(audio_path)
            if audio_duration is not None and self.check_audio_correct(video_path, audio_path):
                return idx, True, "已存在且正确", audio_path.stat().st_size, audio_duration

            # 音频不正确，删除并重新提取
            try:
                audio_path.unlink()
            except:
                pass
        
        # 提取音频
        try:
            cmd = [
                str(self.ffmpeg_path),
                '-i', str(video_path),
                '-vn',  # 禁用视频
                '-acodec', 'libmp3lame',
                '-q:a', '2',  # 音频质量（0-9，2为高质量）
                '-y',  # 覆盖输出文件
                str(audio_path)
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=300,  # 5分钟超时
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0 and audio_path.exists():
                size = audio_path.stat().st_size
                audio_duration = self.get_duration(audio_path) or 0
                # 验证提取的音频
                if audio_duration and self.check_audio_correct(video_path, audio_path):
                    return idx, True, "提取成功", size, audio_duration
                else:
                    return idx, False, "提取后验证失败", 0, audio_duration
            else:
                return idx, False, f"ffmpeg错误: {result.returncode}", 0, 0
                
        except subprocess.TimeoutExpired:
            return idx, False, "超时", 0, 0
        except Exception as e:
            return idx, False, f"异常: {str(e)}", 0, 0
    
    def process_videos(self, video_paths, num_processes):
        """处理视频列表"""
        total = len(video_paths)
        
        # 创建任务列表
        tasks = [(i, str(path)) for i, path in enumerate(video_paths)]
        
        print(f"开始处理 {total} 个视频文件")
        print(f"使用 {num_processes} 个进程")
        print(f"输出目录: {self.output_dir}")
        print("-" * 60)
        
        start_time = time.time()
        processed = 0
        success = 0
        failed = 0
        skipped = 0
        total_size = 0
        
        # 使用进程池
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            # 提交所有任务
            future_to_task = {executor.submit(self.extract_audio, task): task for task in tasks}
            
            # 处理结果
            for future in as_completed(future_to_task):
                idx, task_success, message, size, duration = future.result()
                processed += 1
                # 在主进程累加总时长（子进程的修改不能反映到主进程）
                if duration:
                    self.total_duration += duration
                
                if task_success:
                    if "已存在" in message:
                        skipped += 1
                        status = "↻"
                    else:
                        success += 1
                        total_size += size
                        status = "✓"
                else:
                    failed += 1
                    status = "✗"
                
                # 显示进度
                elapsed = time.time() - start_time
                progress = processed / total * 100
                
                print(f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                      f"{status} {idx+1:03d}.mp3: {message}")
                
                # 每处理10个文件显示一次汇总
                if processed % 10 == 0:
                    print(f"\n[进度] {processed}/{total} ({progress:.1f}%) | "
                          f"成功: {success} | 失败: {failed} | 跳过: {skipped}")
                    if processed > 0:
                        time_per_file = elapsed / processed
                        remaining = total - processed
                        eta = time_per_file * remaining
                        print(f"[时间] 已用: {time.strftime('%H:%M:%S', time.gmtime(elapsed))} | "
                              f"预计剩余: {time.strftime('%H:%M:%S', time.gmtime(eta))}")
        
        # 最终统计
        total_time = time.time() - start_time
        
        print("\n" + "=" * 60)
        print("处理完成!")
        print("=" * 60)
        print(f"总时长: {self.total_duration/3600:.2f} 小时")
        print(f"总文件数: {total}")
        print(f"成功提取: {success}")
        print(f"处理失败: {failed}")
        print(f"跳过文件: {skipped}")
        print(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        print(f"总大小: {total_size/1024/1024/1024:.2f} GB")
        
        if processed > 0:
            print(f"平均速度: {processed/(total_time/60):.1f} 文件/分钟")
        
        return success, failed, skipped

def main():
    parser = argparse.ArgumentParser(description='健壮的音频提取工具')
    parser.add_argument('--input', '-i', default='../videos.json',
                       help='视频列表JSON文件路径 (默认: ../videos.json)')
    parser.add_argument('--output', '-o', default='../audios',
                       help='输出目录路径 (默认: ../audios)')
    parser.add_argument('--ffmpeg', '-f', 
                       default='../ffmpeg.exe',
                       help='ffmpeg可执行文件路径')
    parser.add_argument('--processes', '-p', type=int, default=None,
                       help=f'并行进程数 (默认: CPU核心数)')
    
    args = parser.parse_args()
    
    # 设置默认进程数
    if args.processes is None:
        args.processes = multiprocessing.cpu_count()
    
    print("=" * 60)
    print("健壮的音频提取工具")
    print("=" * 60)
    
    # 检查ffmpeg
    ffmpeg_path = Path(args.ffmpeg)
    if not ffmpeg_path.exists():
        print(f"错误: ffmpeg未找到: {ffmpeg_path}")
        return
    
    # 读取视频列表
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 输入文件未找到: {input_path}")
        return
    
    print(f"读取视频列表: {input_path}")
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        video_paths = json.load(f)
    
    # 转换为Path对象并检查存在性
    videos = []
    missing = []
    for i, path in enumerate(video_paths):
        video_path = Path(path)
        if video_path.exists():
            videos.append(video_path)
        else:
            missing.append((i, path))
    
    if missing:
        print(f"警告: 发现 {len(missing)} 个不存在的视频文件")
        for i, path in missing[:5]:
            print(f"  {i+1:03d}.mp3: {path}")
        if len(missing) > 5:
            print(f"  ... 还有 {len(missing)-5} 个")
        print()
    
    print(f"总视频数: {len(video_paths)}")
    print(f"有效视频: {len(videos)}")
    print(f"ffmpeg路径: {ffmpeg_path}")
    print(f"并行进程: {args.processes}")
    print(f"输出目录: {args.output}")
    
    # 创建提取器
    extractor = AudioExtractor(ffmpeg_path, args.output)
    
    # 开始处理
    success, failed, skipped = extractor.process_videos(videos, args.processes)
    
    # 显示最终结果
    print(f"\n输出目录内容:")
    output_dir = Path(args.output)
    if output_dir.exists():
        mp3_files = list(output_dir.glob("*.mp3"))
        if mp3_files:
            mp3_files.sort()
            print(f"MP3文件数: {len(mp3_files)}")
            
            # 检查编号连续性
            numbers = []
            for f in mp3_files:
                try:
                    num = int(f.stem)
                    numbers.append(num)
                except:
                    pass
            
            if numbers:
                print(f"编号范围: {min(numbers):03d} 到 {max(numbers):03d}")
                
                # 检查缺失的编号
                expected = set(range(1, len(video_paths) + 1))
                actual = set(numbers)
                missing = sorted(list(expected - actual))
                
                if missing:
                    print(f"缺失编号: {len(missing)} 个")
                    for num in missing[:10]:
                        print(f"  {num:03d}.mp3")
                    if len(missing) > 10:
                        print(f"  ... 还有 {len(missing)-10} 个")
                else:
                    print("✓ 所有编号连续完整")
        else:
            print("输出目录为空")
    
    print("\n完成!")

if __name__ == "__main__":
    # Windows多进程支持
    if sys.platform == 'win32':
        multiprocessing.freeze_support()
    
    main()