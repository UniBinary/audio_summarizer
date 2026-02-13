#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健壮的音频提取工具
功能：
1. 多进程并行提取音频
2. 自动检查已存在音频的正确性（时长匹配）
3. 不正确的音频自动重新提取
4. 支持命令行参数配置
5. 跳过已经是音频的输入文件
6. 将成功提取的音频路径写回输入 JSON（保留索引）
"""

import json
import subprocess
import time 
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

class AudioExtractor:
    VIDEO_EXTENSIONS = {
        # 视频格式
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.mpg', '.mpeg'
    }

    AUDIO_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'
    }


    def __init__(self, ffmpeg_path, output_dir, logger, input_json=None, num_processes=None):
        """
        初始化音频提取器
        
        Args:
            ffmpeg_path: ffmpeg可执行文件路径
            output_dir: 输出目录路径
            logger: 日志记录器对象
            input_json: 输入JSON文件路径（包含视频列表）
            num_processes: 并行进程数，默认为CPU核心数
        """
        self.ffmpeg_path = ffmpeg_path
        self.output_dir = output_dir
        self.logger = logger
        self.input_json = input_json
        self.num_processes = num_processes
        
        # 初始化类内变量
        self.video_paths = []
        self.missing_videos = []
        self.total_duration = 0
        self.total_files = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_size = 0
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置logger
        self._setup_logger()
    
    def _setup_logger(self):
        # 如果用户传入 logger，此处可做额外配置；保留占位以避免 AttributeError
        if not hasattr(self.logger, 'info'):
            class Dummy:
                def info(self, *a, **k): pass
                def warning(self, *a, **k): pass
                def error(self, *a, **k): pass
                def debug(self, *a, **k): pass
            self.logger = Dummy()
    
    def _load_video_list(self):
        """从JSON文件加载视频列表"""
        if not self.input_json or not self.input_json.exists():
            self.logger.error(f"输入文件未找到: {self.input_json}")
            return False
        
        self.logger.info(f"读取视频列表: {self.input_json}")
        try:
            with open(self.input_json, 'r', encoding='utf-8-sig') as f:
                self.video_paths = json.load(f)
        except Exception as e:
            self.logger.error(f"读取JSON文件失败: {e}")
            return False
        
        return True
    
    def _get_duration(self, file_path):
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
        except Exception as e:
            self.logger.debug(f"获取文件时长失败 {file_path}: {e}")
        return None
    
    def _check_audio_correct(self, video_path, audio_path):
        """检查音频文件是否正确（时长匹配）"""
        if not audio_path.exists():
            return False
        
        # 获取视频和音频时长
        video_duration = self._get_duration(video_path)
        audio_duration = self._get_duration(audio_path)
        
        self.logger.debug(f"检查: {audio_path} | 视频时长: {video_duration} 秒 | 音频时长: {audio_duration} 秒")

        if video_duration is None or audio_duration is None:
            self.logger.debug("无法获取时长")
            return False  # 无法验证，假设不正确

        # 检查时长差异（允许5秒差异）
        duration_diff = abs(video_duration - audio_duration)
        return duration_diff <= 5
    
    def _extract_audio(self, task):
        """提取单个音频文件
        返回: (idx, success_bool, message, audio_path_str, size_bytes, duration_sec)
        """
        idx, video_path = task
        input_path = Path(video_path)
        audio_path = self.output_dir / f"{idx+1:03d}.mp3"  # 001.mp3 对应 videos[0]
        
        # 如果输入本身就是音频，则跳过处理（不复制）
        if input_path.suffix.lower() in self.AUDIO_EXTENSIONS:
            if input_path.exists():
                audio_duration = self._get_duration(input_path) or 0
                size = input_path.stat().st_size if input_path.exists() else 0
                return idx, True, "输入为音频，跳过", str(input_path), size, audio_duration
            else:
                return idx, False, "输入音频文件不存在", "", 0, 0
        
        # 检查输出目录中编号对应的音频文件是否正确
        if audio_path.exists():
            audio_duration = self._get_duration(audio_path)
            if audio_duration is not None and self._check_audio_correct(input_path, audio_path):
                return idx, True, "已存在且正确", str(audio_path), audio_path.stat().st_size, audio_duration

            # 音频不正确，删除并重新提取
            try:
                audio_path.unlink()
                self.logger.debug(f"删除不正确的音频文件: {audio_path}")
            except Exception as e:
                self.logger.debug(f"删除文件失败 {audio_path}: {e}")
        
        # 提取音频
        try:
            cmd = [
                str(self.ffmpeg_path),
                '-i', str(input_path),
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
                audio_duration = self._get_duration(audio_path) or 0
                # 验证提取的音频
                if audio_duration and self._check_audio_correct(input_path, audio_path):
                    return idx, True, "提取成功", str(audio_path), size, audio_duration
                else:
                    return idx, False, "提取后验证失败", "", 0, audio_duration
            else:
                return idx, False, f"ffmpeg错误: {result.returncode}", "", 0, 0
                
        except subprocess.TimeoutExpired:
            return idx, False, "超时", "", 0, 0
        except Exception as e:
            return idx, False, f"异常: {str(e)}", "", 0, 0

    def _check_output_directory(self):
        """检查输出目录内容"""
        self.logger.info(f"\n输出目录内容:")
        if self.output_dir.exists():
            mp3_files = list(self.output_dir.glob("*.mp3"))
            if mp3_files:
                mp3_files.sort()
                self.logger.info(f"MP3文件数: {len(mp3_files)}")
                
                # 检查编号连续性
                numbers = []
                for f in mp3_files:
                    try:
                        num = int(f.stem)
                        numbers.append(num)
                    except:
                        pass
                
                if numbers:
                    self.logger.info(f"编号范围: {min(numbers):03d} 到 {max(numbers):03d}")
                    
                    # 检查缺失的编号
                    expected = set(range(1, self.total_files + 1))
                    actual = set(numbers)
                    missing = sorted(list(expected - actual))
                    
                    if missing:
                        self.logger.warning(f"缺失编号: {len(missing)} 个")
                        for num in missing[:10]:
                            self.logger.warning(f"  {num:03d}.mp3")
                        if len(missing) > 10:
                            self.logger.warning(f"  ... 还有 {len(missing)-10} 个")
                    else:
                        self.logger.info("✓ 所有编号连续完整")
            else:
                self.logger.info("输出目录为空")

    def process_videos(self):
        """处理视频列表"""
        # 加载视频列表
        if not self._load_video_list():
            self.logger.error("加载视频列表失败")
            return False
        
        # 重置统计信息
        self.total_duration = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_size = 0

        # 设置总文件数（用于编号检查）
        self.total_files = len(self.video_paths)
        
        self.logger.info(f"开始处理 {len(self.video_paths)} 个文件")
        self.logger.info(f"使用 {self.num_processes} 个进程")
        self.logger.info(f"输出目录: {self.output_dir}")
        self.logger.info("-" * 60)
        
        start_time = time.time()
        processed = 0
        total = len(self.video_paths)
        
        # 创建任务列表
        tasks = [(i, str(path)) for i, path in enumerate(self.video_paths)]
        
        # 存放成功提取并需写回 JSON 的映射 idx -> audio_path
        extracted_map = {}
        
        # 使用进程池
        with ProcessPoolExecutor(max_workers=self.num_processes) as executor:
            # 提交所有任务
            future_to_task = {executor.submit(self._extract_audio, task): task for task in tasks}
            
            # 处理结果
            for future in as_completed(future_to_task):
                try:
                    idx, task_success, message, audio_path_str, size, duration = future.result()
                except Exception as e:
                    # 捕获子进程异常
                    self.logger.error(f"任务异常: {e}")
                    processed += 1
                    self.failed_count += 1
                    continue

                processed += 1
                
                # 在主进程累加总时长
                if duration:
                    self.total_duration += duration
                
                if task_success:
                    if "已存在" in message:
                        self.skipped_count += 1
                        status = "↻"
                    else:
                        self.success_count += 1
                        if size:
                            self.total_size += size
                        status = "✓"
                else:
                    self.failed_count += 1
                    status = "✗"
                
                # 如果是提取成功，记录以便写回 JSON
                if task_success and message == "提取成功" and audio_path_str:
                    extracted_map[idx] = audio_path_str
                
                # 显示进度
                elapsed = time.time() - start_time
                progress = processed / total * 100
                
                log_msg = f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] {status} {idx+1:03d}.mp3: {message}"
                self.logger.info(log_msg)
                
                # 每处理10个文件显示一次汇总
                if processed % 10 == 0:
                    summary = f"[进度] {processed}/{total} ({progress:.1f}%) | 成功: {self.success_count} | 失败: {self.failed_count} | 跳过: {self.skipped_count}"
                    self.logger.info(summary)
                    
                    if processed > 0:
                        time_per_file = elapsed / processed
                        remaining = total - processed
                        eta = time_per_file * remaining
                        time_info = f"[时间] 已用: {time.strftime('%H:%M:%S', time.gmtime(elapsed))} | 预计剩余: {time.strftime('%H:%M:%S', time.gmtime(eta))}"
                        self.logger.info(time_info)
        
        # 将成功提取的音频路径写回输入 JSON（保持索引一致）
        if extracted_map and self.input_json and self.input_json.exists():
            try:
                with open(self.input_json, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                # 确保 data 是列表
                if isinstance(data, list):
                    for idx, audio_path in extracted_map.items():
                        if 0 <= idx < len(data):
                            data[idx] = audio_path
                    # 备份原文件（可选）
                    try:
                        backup = self.input_json.with_suffix(self.input_json.suffix + '.bak')
                        with open(backup, 'w', encoding='utf-8') as b:
                            json.dump(json.load(open(self.input_json, 'r', encoding='utf-8-sig')), b, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    # 写回
                    with open(self.input_json, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        self.logger.info(f"已将 {len(extracted_map)} 个提取成功的音频路径写回 {self.input_json}")
                else:
                    self.logger.warning("输入 JSON 不是列表，跳过写回操作")
            except Exception as e:
                self.logger.error(f"写回输入 JSON 失败: {e}")
        
        # 最终统计
        total_time = time.time() - start_time
        
        self.logger.info("=" * 60)
        self.logger.info("处理完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"总时长: {self.total_duration/3600:.2f} 小时")
        self.logger.info(f"总文件数: {self.total_files}")
        self.logger.info(f"成功提取: {self.success_count}")
        self.logger.info(f"处理失败: {self.failed_count}")
        self.logger.info(f"跳过文件: {self.skipped_count}")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        self.logger.info(f"总大小: {self.total_size/1024/1024/1024:.2f} GB")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文件/分钟")
        
        # 检查输出目录内容
        self._check_output_directory()
        
        return self.success_count > 0
