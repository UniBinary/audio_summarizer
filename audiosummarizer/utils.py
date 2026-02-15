import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import List, Set
from concurrent.futures import ProcessPoolExecutor, as_completed

class AudioFinder:
    """音频文件查找器类"""
    
    # 支持的音视频文件扩展名
    SUPPORTED_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus',
        # 视频格式
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.mpg', '.mpeg'
    }
    
    def __init__(self, logger, input_dir: Path, output_json: Path):
        """
        初始化音频查找器
        
        Args:
            logger: 日志记录器对象
            input_dir: 输入目录路径，递归遍历此目录寻找音视频文件
            output_json: 输出JSON文件路径
        """
        self.logger = logger
        self.input_dir = input_dir
        self.output_json = output_json
        
        # 存储类内数据
        self.audio_files: List[str] = []
        self.processed_dirs: Set[Path] = set()
        self.skipped_dirs: Set[Path] = set()
        self.total_files_found = 0
        
        # 配置logger
        self._setup_logger()
        
        # 验证目录
        self._validate_directories()
    
    def _validate_directories(self) -> None:
        """验证输入和输出目录"""
        # 验证输入目录
        if not self.input_dir.exists():
            self.logger.error(f"输入目录不存在: {self.input_dir}")
            raise FileNotFoundError(f"输入目录不存在: {self.input_dir}")
        
        if not self.input_dir.is_dir():
            self.logger.error(f"输入路径不是目录: {self.input_dir}")
            raise NotADirectoryError(f"输入路径不是目录: {self.input_dir}")
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"输出目录已创建/确认: {self.output_dir}")
    
    def _is_audio_video_file(self, file_path: Path) -> bool:
        """
        检查文件是否为音视频文件
        
        Args:
            file_path: 文件路径对象
            
        Returns:
            bool: 如果是音视频文件返回True，否则返回False
        """
        # 检查扩展名
        extension = file_path.suffix.lower()
        return extension in self.SUPPORTED_EXTENSIONS
    
    def _should_skip_directory(self, dir_path: Path) -> bool:
        """
        判断是否应该跳过某个目录
        
        Args:
            dir_path: 目录路径对象
            
        Returns:
            bool: 如果应该跳过返回True，否则返回False
        """
        # 跳过系统目录和隐藏目录
        dir_name = dir_path.name.lower()
        
        # 常见的系统目录和不需要遍历的目录
        skip_patterns = {
            '$recycle.bin', 'recycle.bin', 'system volume information',
            'temp', 'tmp', 'cache', 'logs', 'log', 'backup', 'backups',
            '.git', '.svn', '.hg', '.idea', '.vscode', '__pycache__',
            'node_modules', 'venv', 'env', '.env', 'virtualenv'
        }
        
        # 检查目录名是否匹配跳过模式
        if dir_name in skip_patterns:
            self.logger.debug(f"跳过系统目录: {dir_path}")
            return True
        
        # 检查是否为隐藏目录（以点开头）
        if dir_name.startswith('.'):
            self.logger.debug(f"跳过隐藏目录: {dir_path}")
            return True
        
        # 检查目录访问权限
        try:
            # 尝试访问目录
            os.access(dir_path, os.R_OK)
            return False
        except PermissionError:
            self.logger.warning(f"跳过无权限目录: {dir_path}")
            return True
        except Exception as e:
            self.logger.warning(f"跳过无法访问的目录 {dir_path}: {e}")
            return True
    
    def _scan_directory(self, current_dir: Path) -> None:
        """
        递归扫描目录，查找音视频文件
        
        Args:
            current_dir: 当前要扫描的目录
        """
        try:
            # 标记目录已处理
            self.processed_dirs.add(current_dir)
            
            # 遍历目录内容
            for item in current_dir.iterdir():
                try:
                    if item.is_file():
                        # 检查是否为音视频文件
                        if self._is_audio_video_file(item):
                            # 获取绝对路径并添加到列表
                            abs_path = str(item.absolute())
                            self.audio_files.append(abs_path)
                            self.total_files_found += 1
                            
                            # 每找到100个文件记录一次
                            if self.total_files_found % 100 == 0:
                                self.logger.info(f"已找到 {self.total_files_found} 个音视频文件")
                    
                    elif item.is_dir():
                        # 递归扫描子目录
                        if not self._should_skip_directory(item):
                            self._scan_directory(item)
                        else:
                            self.skipped_dirs.add(item)
                
                except PermissionError:
                    self.logger.warning(f"无权限访问: {item}")
                    continue
                except Exception as e:
                    self.logger.warning(f"处理 {item} 时出错: {e}")
                    continue
        
        except Exception as e:
            self.logger.error(f"扫描目录 {current_dir} 时出错: {e}")
    
    def _save_to_json(self) -> bool:
        """
        将音频文件列表保存为JSON文件
        
        Returns:
            bool: 保存成功返回True，否则返回False
        """
        try:
            # 准备输出文件路径
            output_file = self.output_json
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入JSON文件
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.audio_files, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"JSON文件已保存: {output_file}")
            self.logger.info(f"共找到 {self.total_files_found} 个音视频文件")
            return True
            
        except Exception as e:
            self.logger.error(f"保存JSON文件失败: {e}")
            return False
    
    def find_and_save(self) -> bool:
        """
        主方法：查找音视频文件并保存为JSON
        
        Returns:
            bool: 操作成功返回True，否则返回False
        """
        self.logger.info("=" * 60)
        self.logger.info("开始查找音视频文件")
        self.logger.info("=" * 60)
        self.logger.info(f"输入目录: {self.input_dir}")
        self.logger.info(f"输出目录: {self.output_dir}")
        self.logger.info(f"支持的文件扩展名: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}")
        
        # 重置统计数据
        self.audio_files.clear()
        self.processed_dirs.clear()
        self.skipped_dirs.clear()
        self.total_files_found = 0
        
        # 开始扫描
        start_time = time.time()
        self._scan_directory(self.input_dir)
        
        # 计算耗时
        elapsed_time = time.time() - start_time
        
        # 显示统计信息
        self.logger.info("=" * 60)
        self.logger.info("扫描完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"扫描耗时: {elapsed_time:.2f} 秒")
        self.logger.info(f"处理目录数: {len(self.processed_dirs)}")
        self.logger.info(f"跳过目录数: {len(self.skipped_dirs)}")
        self.logger.info(f"找到音视频文件数: {self.total_files_found}")
        
        if self.total_files_found == 0:
            self.logger.warning("未找到任何音视频文件!")
            return False
        
        # 保存为JSON
        self.logger.info("-" * 60)
        self.logger.info("正在保存JSON文件...")
        
        if self._save_to_json():
            # 显示一些示例文件
            self.logger.info("-" * 60)
            self.logger.info("示例文件 (前10个):")
            for i, file_path in enumerate(self.audio_files[:10], 1):
                self.logger.info(f"  {i:3d}. {os.path.basename(file_path)}")
            
            if len(self.audio_files) > 10:
                self.logger.info(f"  ... 还有 {len(self.audio_files) - 10} 个文件")
            
            return True
        else:
            return False
    
    def get_statistics(self) -> dict:
        """
        获取统计信息
        
        Returns:
            dict: 包含统计信息的字典
        """
        return {
            "total_files": self.total_files_found,
            "processed_dirs": len(self.processed_dirs),
            "skipped_dirs": len(self.skipped_dirs),
            "audio_files": self.audio_files[:10] if self.audio_files else []  # 只返回前10个作为示例
        }



class AudioExtractor:
    AUDIO_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'
    }

    def __init__(self, logger, ffmpeg_path : Path, output_dir : Path, input_json : Path, output_json : Path, num_processes : int = 1):
        """
        初始化音频提取器
        
        Args:
            logger: 日志记录器对象
            ffmpeg_path: ffmpeg可执行文件路径
            output_dir: 输出目录路径
            input_json: 输入JSON文件路径（包含视频列表）
            output_json: 输出JSON文件路径
            num_processes: 并行进程数，默认为CPU核心数，默认为1，表示不使用并行
        """
        self.ffmpeg_path = ffmpeg_path
        self.output_dir = output_dir
        self.logger = logger
        self.input_json = input_json
        self.output_json = output_json
        self.num_processes = num_processes
        
        # 初始化类内变量
        self.video_paths = []
        self.missing_videos = []
        self.already_an_audio = []
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
        self.logger.info(f"读取视频列表: {self.input_json}")
        try:
            with open(str(self.input_json), 'r', encoding='utf-8-sig') as f:
                self.video_paths = json.load(f)
        except FileNotFoundError:
            self.logger.error(f"输入JSON文件不存在: {self.input_json}")
            return False
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
                size = input_path.stat().st_size
                self.already_an_audio.append(input_path)
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
                    
                    skipped = set()
                    for already in self.already_an_audio:
                        try:
                            num = self.video_paths.index(str(already)) + 1  # 视频列表索引 +1 对应编号
                            skipped.add(num)
                        except:
                            pass

                    # 从缺失编号中排除已跳过的编号
                    missing = [num for num in missing if num not in skipped]

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
                with open(str(self.input_json), 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                # 确保 data 是列表
                if isinstance(data, list):
                    for idx, audio_path in extracted_map.items():
                        if 0 <= idx < len(data):
                            data[idx] = audio_path
                    # 写回
                    with open(str(self.output_json), 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        self.logger.info(f"已将 {len(extracted_map)} 个提取成功的音频路径写回 {self.output_json}")
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



class OSSUploader:
    def __init__(self, logger, input_json):
        self.logger = logger
        self.input_json = input_json

# 其他实现



class AudioTranscriber:
    def __init__(self, logger, bucket_name, bucket_endpoint, access_key_id, access_key_secret, output_dir):
        self.logger = logger
        self.bucket_name = bucket_name
        self.bucket_endpoint = bucket_endpoint
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.output_dir = output_dir

# 其他实现



class TextSummarizer:
    def __init__(self, logger, model_api_key, output_dir):
        self.logger = logger
        self.model_api_key = model_api_key
        self.output_dir = output_dir