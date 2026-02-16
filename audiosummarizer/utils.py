import os
import sys
import oss2
import json
import time
import logging
import dashscope
import subprocess
from pathlib import Path
from openai import OpenAI
from urllib import request
from http import HTTPStatus
from typing import List, Set, Dict, Union
from dashscope.audio.asr import Transcription
from concurrent.futures import ProcessPoolExecutor, as_completed

class AVFinder:
    """寻找音视频文件类"""
    
    # 支持的音视频文件扩展名
    SUPPORTED_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus',
        # 视频格式
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.mpg', '.mpeg'
    }
    
    def __init__(self, input_dir: Union[str, Path], output_json: Union[str, Path], logger=None, log_file: Union[str, Path] = None):
        """
        初始化音视频文件查找器
        
        Args:
            input_dir: 输入目录路径，递归遍历此目录寻找音视频文件
            output_json: 输出的含有音视频文件路径列表的JSON文件路径
            logger: 日志记录器对象，若为空则自行创建
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
        """
        self.input_dir = Path(input_dir)
        self.output_json = Path(output_json)
        self.log_file = Path(log_file) if log_file else None
        
        # 设置logger
        if logger is None:
            self._setup_logger()
        else:
            self.logger = logger
        
        # 存储类内数据
        self.audio_files: List[str] = []
        self.processed_dirs: Set[Path] = set()
        self.skipped_dirs: Set[Path] = set()
        self.total_files_found = 0
        
        # 验证目录
        self._validate_directories()
    
    def _setup_logger(self):
        self.logger = logging.getLogger("AVFinder")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter('[AVFinder] %(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
        
            # 文件handler
            if self.log_file:
                # 使用自定义日志文件
                log_file_path = Path(self.log_file)
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用自定义日志文件: {log_file_path}")
            else:
                # 使用默认日志文件
                output_dir = self.output_json.parent
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = output_dir / "AVFinder.log"
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用默认日志文件: {log_file_path}")
            
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('[AVFinder] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

    def _validate_directories(self) -> None:
        """验证输入和输出目录"""
        # 验证输入目录
        if not self.input_dir.exists():
            self.logger.error(f"输入目录不存在: {self.input_dir}")
            raise FileNotFoundError(f"输入目录不存在: {self.input_dir}")
        
        if not self.input_dir.is_dir():
            self.logger.error(f"输入路径不是目录: {self.input_dir}")
            raise NotADirectoryError(f"输入路径不是目录: {self.input_dir}")
        
        # 创建输出目录（如果输出JSON文件路径的父目录不存在）
        self.output_json.parent.mkdir(parents=True, exist_ok=True)
    
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
            with open(str(output_file), 'w', encoding='utf-8') as f:
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
        self.logger.info(f"输出JSON: {self.output_json}")
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
    """提取音频类"""
    
    AUDIO_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'
    }

    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], audio_dir: Union[str, Path], 
                 ffmpeg_path: Union[str, Path], ffprobe_path: Union[str, Path], num_processes: int = 1, logger=None, 
                 log_file: Union[str, Path] = None):
        """
        初始化音频提取器
        
        Args:
            input_json: 输入的含有音视频文件路径列表的JSON文件路径
            output_json: 输出的包含原有的音频文件和从视频中提取的音频文件的路径列表的JSON文件路径
            audio_dir: 提取后的音频存放目录路径
            ffmpeg_path: ffmpeg可执行文件路径
            ffprobe_path: ffprobe可执行文件路径
            num_processes: 并行进程数，默认为1
            logger: 日志记录器对象，若为空则自行创建
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
        """
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.audio_dir = Path(audio_dir)
        self.ffmpeg_path = Path(ffmpeg_path)
        self.ffprobe_path = Path(ffprobe_path)
        self.num_processes = num_processes
        self.log_file = Path(log_file) if log_file else None
        
        # 设置logger
        if logger is None:
            self._setup_logger()
        else:
            self.logger = logger
        
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
        self.audio_dir.mkdir(parents=True, exist_ok=True)
    
    def _setup_logger(self):
        self.logger = logging.getLogger("AudioExtractor")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter('[AudioExtractor] %(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
        
            # 文件handler
            if self.log_file:
                # 使用自定义日志文件
                log_file_path = Path(self.log_file)
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用自定义日志文件: {log_file_path}")
            else:
                # 使用默认日志文件
                output_dir = self.audio_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = output_dir / "AudioExtractor.log"
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用默认日志文件: {log_file_path}")
            
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('[AudioExtractor] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
    
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
        
        # 获取文件扩展名
        extension = input_path.suffix.lower()
        
        # 如果输入本身就是音频，则跳过处理（不复制）
        if extension in self.AUDIO_EXTENSIONS:
            if input_path.exists():
                audio_duration = self._get_duration(input_path) or 0
                size = input_path.stat().st_size
                self.already_an_audio.append(input_path)
                return idx, True, "输入为音频，跳过", str(input_path), size, audio_duration
            else:
                return idx, False, "输入音频文件不存在", "", 0, 0
        
        # 生成音频文件名：索引+1，补齐三位数，保持原扩展名
        audio_filename = f"{idx+1:03d}.mp3"
        audio_path = self.audio_dir / audio_filename
        
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
        self.logger.info(f"音频目录内容:")
        if self.audio_dir.exists():
            # 获取所有音频文件
            audio_files = []
            for ext in self.AUDIO_EXTENSIONS:
                audio_files.extend(list(self.audio_dir.glob(f"*{ext}")))
            
            if audio_files:
                audio_files.sort()
                self.logger.info(f"音频文件数: {len(audio_files)}")
                
                # 检查编号连续性
                numbers = []
                for f in audio_files:
                    try:
                        # 提取数字部分（文件名中的数字）
                        num_str = ''.join(filter(str.isdigit, f.stem))
                        if num_str:
                            num = int(num_str)
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
                            self.logger.warning(f"  {num:03d}")
                        if len(missing) > 10:
                            self.logger.warning(f"  ... 还有 {len(missing)-10} 个")
                    else:
                        self.logger.info("✓ 所有编号连续完整")
            else:
                self.logger.info("音频目录为空")

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
        self.logger.info(f"音频目录: {self.audio_dir}")
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
                    if "输入为音频" in message:
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
                if task_success and audio_path_str:
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
        
        # 将成功提取的音频路径写回输出 JSON（保持索引一致）
        if extracted_map:
            try:
                # 创建输出列表，用音频路径覆盖原视频路径
                output_list = []
                for idx in range(len(self.video_paths)):
                    if idx in extracted_map:
                        output_list.append(extracted_map[idx])
                    else:
                        # 如果该索引没有提取成功，保持原路径
                        output_list.append(self.video_paths[idx])
                
                # 写回输出JSON
                with open(str(self.output_json), 'w', encoding='utf-8') as f:
                    json.dump(output_list, f, ensure_ascii=False, indent=2)
                    self.logger.info(f"已将 {len(extracted_map)} 个提取成功的音频路径写入 {self.output_json}")
            except Exception as e:
                self.logger.error(f"写入输出 JSON 失败: {e}")
        
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
    """上传音频到OSS类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], bucket_name: str, 
                 bucket_endpoint: str, access_key_id: str, access_key_secret: str, 
                 num_processes: int = 1, logger=None, log_file: Union[str, Path] = None):
        """
        初始化OSS上传器
        
        Args:
            input_json: 输入的包含原有的音频文件和从视频中提取的音频文件的路径列表的JSON文件路径
            output_json: 输出的包含所有音频文件的公网URL的JSON文件路径
            bucket_name: 阿里云OSS存储桶名
            bucket_endpoint: 阿里云OSS存储桶endpoint
            access_key_id: 阿里云access key ID
            access_key_secret: 阿里云access key secret
            num_processes: 并行进程数，默认为1
            logger: 日志记录器对象，若为空则自行创建
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
        """
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.bucket_name = bucket_name
        self.bucket_endpoint = bucket_endpoint
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.num_processes = num_processes
        self.log_file = Path(log_file) if log_file else None
        
        # 设置logger
        if logger is None:
            self._setup_logger()
        else:
            self.logger = logger
        
        # 初始化OSS客户端
        try:
            auth = oss2.Auth(self.access_key_id, self.access_key_secret)
            self.bucket = oss2.Bucket(auth, self.bucket_endpoint, self.bucket_name)
            self.logger.info(f"OSS客户端初始化成功，存储桶: {self.bucket_name}")
        except ImportError:
            self.logger.error("请安装 oss2 库: pip install oss2")
            raise
        except Exception as e:
            self.logger.error(f"OSS客户端初始化失败: {e}")
            raise
        
        # 初始化统计信息
        self.total_files = 0
        self.success_count = 0
        self.failed_count = 0
        self.uploaded_urls = []
    
    def _load_file_list(self) -> List[str]:
        """从JSON文件加载文件列表"""
        self.logger.info(f"读取文件列表: {self.input_json}")
        try:
            with open(str(self.input_json), 'r', encoding='utf-8') as f:
                file_list = json.load(f)
            
            if not isinstance(file_list, list):
                self.logger.error(f"JSON文件不是列表格式: {self.input_json}")
                return []
            
            self.total_files = len(file_list)
            self.logger.info(f"找到 {self.total_files} 个文件需要上传")
            return file_list
            
        except FileNotFoundError:
            self.logger.error(f"输入JSON文件不存在: {self.input_json}")
            return []
        except Exception as e:
            self.logger.error(f"读取JSON文件失败: {e}")
            return []
    
    def _upload_single_file(self, task):
        """上传单个文件到OSS
        返回: (idx, success_bool, message, url)
        """
        idx, file_path = task
        file_path_obj = Path(file_path)
        
        # 生成OSS对象名: oss://audios/<索引+1，补齐三位数>.<后缀名>
        extension = file_path_obj.suffix.lower()
        object_name = f"audios/{idx+1:03d}{extension}"
        
        try:
            # 检查文件是否存在
            if not file_path_obj.exists():
                return idx, False, "本地文件不存在", ""
            
            # 上传文件到OSS
            self.logger.debug(f"上传文件: {file_path} -> {object_name}")
            self.bucket.put_object_from_file(object_name, str(file_path_obj))
            
            # 生成可访问的URL（有效期1天）
            url = self.bucket.sign_url('GET', object_name, 86400)
            
            return idx, True, "上传成功", url
            
        except Exception as e:
            self.logger.debug(f"上传失败 {file_path}: {e}")
            return idx, False, f"上传失败: {str(e)}", ""
    
    def upload_files(self) -> bool:
        """上传所有文件到OSS"""
        # 加载文件列表
        file_list = self._load_file_list()
        if not file_list:
            self.logger.error("没有找到需要上传的文件")
            return False
        
        self.logger.info(f"开始上传 {len(file_list)} 个文件")
        self.logger.info(f"使用 {self.num_processes} 个进程")
        self.logger.info(f"存储桶: {self.bucket_name}")
        self.logger.info("-" * 60)
        
        start_time = time.time()
        processed = 0
        total = len(file_list)
        
        # 创建任务列表
        tasks = [(i, str(path)) for i, path in enumerate(file_list)]
        
        # 初始化URL列表
        self.uploaded_urls = [""] * total
        
        # 使用进程池
        with ProcessPoolExecutor(max_workers=self.num_processes) as executor:
            # 提交所有任务
            future_to_task = {executor.submit(self._upload_single_file, task): task for task in tasks}
            
            # 处理结果
            for future in as_completed(future_to_task):
                try:
                    idx, task_success, message, url = future.result()
                except Exception as e:
                    # 捕获子进程异常
                    self.logger.error(f"任务异常: {e}")
                    processed += 1
                    self.failed_count += 1
                    continue

                processed += 1
                
                if task_success:
                    self.success_count += 1
                    self.uploaded_urls[idx] = url
                    status = "✓"
                else:
                    self.failed_count += 1
                    status = "✗"
                
                # 显示进度
                elapsed = time.time() - start_time
                progress = processed / total * 100
                
                log_msg = f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] {status} {idx+1:03d}: {message}"
                self.logger.info(log_msg)
                
                # 每处理10个文件显示一次汇总
                if processed % 10 == 0:
                    summary = f"[进度] {processed}/{total} ({progress:.1f}%) | 成功: {self.success_count} | 失败: {self.failed_count}"
                    self.logger.info(summary)
                    
                    if processed > 0:
                        time_per_file = elapsed / processed
                        remaining = total - processed
                        eta = time_per_file * remaining
                        time_info = f"[时间] 已用: {time.strftime('%H:%M:%S', time.gmtime(elapsed))} | 预计剩余: {time.strftime('%H:%M:%S', time.gmtime(eta))}"
                        self.logger.info(time_info)
        
        # 保存URL列表到输出JSON
        try:
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(self.uploaded_urls, f, ensure_ascii=False, indent=2)
            self.logger.info(f"URL列表已保存到: {self.output_json}")
        except Exception as e:
            self.logger.error(f"保存URL列表失败: {e}")
            return False
        
        # 最终统计
        total_time = time.time() - start_time
        
        self.logger.info("=" * 60)
        self.logger.info("上传完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"总文件数: {self.total_files}")
        self.logger.info(f"上传成功: {self.success_count}")
        self.logger.info(f"上传失败: {self.failed_count}")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文件/分钟")
        
        return self.success_count > 0
    
    def _setup_logger(self):
        self.logger = logging.getLogger("OSSUploader")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter('[OSSUploader] %(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
        
            # 文件handler
            if self.log_file:
                # 使用自定义日志文件
                log_file_path = Path(self.log_file)
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用自定义日志文件: {log_file_path}")
            else:
                # 使用默认日志文件
                output_dir = self.output_json.parent
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = output_dir / "OSSUploader.log"
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用默认日志文件: {log_file_path}")
            
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('[OSSUploader] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)



class AudioTranscriber:
    """音频转文字类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], text_dir: Union[str, Path], 
                 model_api_key: str, num_processes: int = 1, logger=None, log_file: Union[str, Path] = None):
        """
        初始化音频转录器
        
        Args:
            input_json: 输入的包含所有音频文件的公网URL的JSON文件路径
            output_json: 输出的包含所有音频转写生成的文字文件的路径的JSON文件路径
            text_dir: 存放音频转写生成的文字文件的文件夹
            model_api_key: Fun-ASR模型API key
            num_processes: 并行进程数，默认为1
            logger: 日志记录器对象，若为空则自行创建
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
        """
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.text_dir = Path(text_dir)
        self.model_api_key = model_api_key
        self.num_processes = num_processes
        self.log_file = Path(log_file) if log_file else None
        
        # 设置logger
        if logger is None:
            self._setup_logger()
        else:
            self.logger = logger
        
        # 初始化统计信息
        self.total_urls = 0
        self.success_count = 0
        self.failed_count = 0
        self.text_file_paths = []
        
        # 创建文本目录
        self.text_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_url_list(self) -> List[str]:
        """从JSON文件加载URL列表"""
        self.logger.info(f"读取URL列表: {self.input_json}")
        try:
            with open(str(self.input_json), 'r', encoding='utf-8') as f:
                url_list = json.load(f)
            
            if not isinstance(url_list, list):
                self.logger.error(f"JSON文件不是列表格式: {self.input_json}")
                return []
            
            self.total_urls = len(url_list)
            self.logger.info(f"找到 {self.total_urls} 个URL需要转录")
            return url_list
            
        except FileNotFoundError:
            self.logger.error(f"输入JSON文件不存在: {self.input_json}")
            return []
        except Exception as e:
            self.logger.error(f"读取JSON文件失败: {e}")
            return []
    
    def _split_urls_into_batches(self, urls: List[str]) -> List[List[str]]:
        """将URL列表分成多个批次
        每个批次最多100个URL，最少分num_processes个批次
        """
        # 如果URL个数小于num_processes，则调整num_processes
        actual_processes = min(self.num_processes, len(urls))
        
        # 计算每个批次的大小
        max_batch_size = 100
        min_batches = actual_processes
        
        # 计算批次数量
        num_batches = max(min_batches, (len(urls) + max_batch_size - 1) // max_batch_size)
        
        # 计算每个批次的大小
        batch_size = (len(urls) + num_batches - 1) // num_batches
        
        # 分割URL列表
        batches = []
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i+batch_size]
            batches.append(batch)
        
        self.logger.info(f"将 {len(urls)} 个URL分成 {len(batches)} 个批次，每个批次最多 {batch_size} 个URL")
        return batches
    
    def _transcribe_batch(self, batch_urls: List[str], batch_index: int) -> List[str]:
        """转录一个批次的音频URL"""
        try:
            
            # 设置API配置
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
            dashscope.api_key = self.model_api_key
            
            # 调用Fun-ASR API
            task_response = Transcription.async_call(
                model='fun-asr',
                file_urls=batch_urls,
                language_hints=['zh',],
                diarization_enabled=True,
            )
            
            transcription_response = Transcription.wait(task=task_response.output.task_id)
            
            results = []
            if transcription_response.status_code == HTTPStatus.OK:
                for transcription in transcription_response.output['results']:
                    if transcription['subtask_status'] == 'SUCCEEDED':
                        url = transcription['transcription_url']
                        result_data = json.loads(request.urlopen(url).read().decode('utf8'))
                        
                        # 格式化转录结果
                        result_str = self._format_transcription_result(result_data)
                        results.append(result_str)
                    else:
                        self.logger.error(f'转录失败: {transcription}')
                        results.append("")  # 失败时返回空字符串
            else:
                self.logger.error(f'Fun-ASR API错误: {transcription_response.output.message}')
                # 返回与音频URL数量相同的空字符串列表
                results = [""] * len(batch_urls)
            
            return results
            
        except ImportError:
            self.logger.error("请安装 dashscope 库: pip install dashscope")
            raise
        except Exception as e:
            self.logger.error(f"转录批次 {batch_index} 失败: {e}")
            # 返回空字符串列表
            return [""] * len(batch_urls)
    
    def _format_transcription_result(self, result_data: Dict) -> str:
        """格式化转录结果为指定的字符串格式"""
        try:
            transcripts = result_data.get("transcripts", [])
            if not transcripts:
                return ""
            
            formatted_lines = []
            
            for transcript in transcripts:
                sentences = transcript.get("sentences", [])
                if not sentences:
                    continue
                
                # 按时间顺序排序句子
                sorted_sentences = sorted(sentences, key=lambda x: x.get("begin_time", 0))
                
                for sentence in sorted_sentences:
                    speaker_id = sentence.get("speaker_id", 0)
                    text = sentence.get("text", "").strip()
                    
                    if text:  # 只添加非空文本
                        # speaker_id从0开始，+1使其从1开始
                        formatted_line = f"{speaker_id + 1}: {text}"
                        formatted_lines.append(formatted_line)
            
            # 将所有行用换行符连接
            result_str = "\n".join(formatted_lines)
            return result_str
            
        except Exception as e:
            self.logger.error(f"格式化转录结果失败: {e}")
            return ""
    
    def transcribe_audio(self) -> bool:
        """转录所有音频"""
        # 加载URL列表
        url_list = self._load_url_list()
        if not url_list:
            self.logger.error("没有找到需要转录的URL")
            return False
        
        # 将URL分成批次
        url_batches = self._split_urls_into_batches(url_list)
        
        self.logger.info(f"开始转录 {len(url_list)} 个音频")
        self.logger.info(f"使用 {len(url_batches)} 个进程")
        self.logger.info(f"文本目录: {self.text_dir}")
        self.logger.info("-" * 60)
        
        start_time = time.time()
        
        # 创建回传字典
        result_dict = {}
        
        # 使用进程池处理批次
        with ProcessPoolExecutor(max_workers=len(url_batches)) as executor:
            # 提交所有批次任务
            future_to_batch = {}
            for i, batch in enumerate(url_batches):
                future = executor.submit(self._transcribe_batch, batch, i)
                future_to_batch[future] = i
            
            # 处理结果
            processed_batches = 0
            total_batches = len(url_batches)
            
            for future in as_completed(future_to_batch):
                batch_index = future_to_batch[future]
                try:
                    batch_results = future.result()
                    result_dict[batch_index] = batch_results
                    
                    processed_batches += 1
                    progress = processed_batches / total_batches * 100
                    
                    elapsed = time.time() - start_time
                    log_msg = f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] ✓ 批次 {batch_index+1}/{total_batches} 完成，处理了 {len(batch_results)} 个音频"
                    self.logger.info(log_msg)
                    
                except Exception as e:
                    self.logger.error(f"批次 {batch_index} 执行失败: {e}")
                    # 为失败的批次添加空结果
                    result_dict[batch_index] = [""] * len(url_batches[batch_index])
        
        # 将回传字典转为列表并展开
        all_results = []
        for batch_index in sorted(result_dict.keys()):
            all_results.extend(result_dict[batch_index])
        
        # 保存转录结果到文件
        self.text_file_paths = []
        for idx, result_text in enumerate(all_results):
            text_filename = f"{idx+1:03d}.txt"
            text_path = self.text_dir / text_filename
            
            try:
                with open(str(text_path), 'w', encoding='utf-8') as f:
                    f.write(result_text)
                
                self.text_file_paths.append(str(text_path))
                
                if result_text.strip():
                    self.success_count += 1
                else:
                    self.failed_count += 1
                    
            except Exception as e:
                self.logger.error(f"保存文本文件失败 {text_filename}: {e}")
                self.text_file_paths.append("")
                self.failed_count += 1
        
        # 保存文本文件路径列表到输出JSON
        try:
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(self.text_file_paths, f, ensure_ascii=False, indent=2)
            self.logger.info(f"文本文件路径列表已保存到: {self.output_json}")
        except Exception as e:
            self.logger.error(f"保存文本文件路径列表失败: {e}")
            return False
        
        # 最终统计
        total_time = time.time() - start_time
        
        self.logger.info("=" * 60)
        self.logger.info("转录完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"总音频数: {self.total_urls}")
        self.logger.info(f"转录成功: {self.success_count}")
        self.logger.info(f"转录失败: {self.failed_count}")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if self.total_urls > 0:
            self.logger.info(f"平均速度: {self.total_urls/(total_time/60):.1f} 音频/分钟")
        
        return self.success_count > 0
    
    def _setup_logger(self):
        self.logger = logging.getLogger("AudioTranscriber")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter('[AudioTranscriber] %(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
        
            # 文件handler
            if self.log_file:
                # 使用自定义日志文件
                log_file_path = Path(self.log_file)
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用自定义日志文件: {log_file_path}")
            else:
                # 使用默认日志文件
                output_dir = self.text_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = output_dir / "AudioTranscriber.log"
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用默认日志文件: {log_file_path}")
            
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('[AudioTranscriber] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)



class TextSummarizer:
    """总结文字类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], summary_dir: Union[str, Path], 
                 model_api_key: str, num_processes: int = 1, origin_json: Union[str, Path] = None, logger=None, 
                 log_file: Union[str, Path] = None):
        """
        初始化文本总结器
        
        Args:
            input_json: 输入的包含所有音频转写生成的文字文件的路径的JSON文件路径
            output_json: 输出的包含所有Deepseek生成的文字总结文件的路径的JSON文件路径
            summary_dir: 存放Deepseek生成的文字总结的文件夹
            model_api_key: Deepseek模型API key
            num_processes: 并行进程数，默认为1
            origin_json: 包含每个文本文件对应的原视频路径的列表的JSON文件路径，若为空则不在生成的总结头部添加原视频路径
            logger: 日志记录器对象，若为空则自行创建
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
        """
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.summary_dir = Path(summary_dir)
        self.model_api_key = model_api_key
        self.num_processes = num_processes
        self.origin_json = Path(origin_json) if origin_json else None
        self.log_file = Path(log_file) if log_file else None
        
        # 设置logger
        if logger is None:
            self._setup_logger()
        else:
            self.logger = logger
        
        # 初始化统计信息
        self.total_texts = 0
        self.success_count = 0
        self.failed_count = 0
        self.summary_file_paths = []
        
        # 创建总结目录
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        
        # 系统提示词
        self.system_prompt = """请总结以下逐字稿的主要内容，每一行是一句话，冒号前是说话人ID，冒号后是说话内容。
要求：使用Markdown格式输出总结，把说话人的意思表达清楚，重要的语段详细一些，6000字以内即可。如果能推断出说话人身份，可以省略说话人ID，直接用身份称呼，并在结尾注明身份对应的说话人ID。
注意：
1.以下文字是AI从音频中识别的，可能会有一些不必要的语气词，请适当忽略。说话人普通话不标准、说话不流利等因素都可能导致识别不准，遇到错误时请适当根据上下文推测。
2.回答开头不要有类似"好的"的语句，直接开始总结。"""
    
    def _load_text_file_paths(self) -> List[str]:
        """从JSON文件加载文本文件路径列表"""
        self.logger.info(f"读取文本文件路径列表: {self.input_json}")
        try:
            with open(str(self.input_json), 'r', encoding='utf-8') as f:
                text_paths = json.load(f)
            
            if not isinstance(text_paths, list):
                self.logger.error(f"JSON文件不是列表格式: {self.input_json}")
                return []
            
            self.total_texts = len(text_paths)
            self.logger.info(f"找到 {self.total_texts} 个文本文件需要总结")
            return text_paths
            
        except FileNotFoundError:
            self.logger.error(f"输入JSON文件不存在: {self.input_json}")
            return []
        except Exception as e:
            self.logger.error(f"读取JSON文件失败: {e}")
            return []
    
    def _load_origin_paths(self) -> List[str]:
        """加载原始视频路径列表"""
        if self.origin_json is None:
            return []
        
        try:
            with open(str(self.origin_json), 'r', encoding='utf-8') as f:
                origin_paths = json.load(f)
            
            if not isinstance(origin_paths, list):
                self.logger.warning(f"原始路径JSON文件不是列表格式: {self.origin_json}")
                return []
            
            return origin_paths
            
        except FileNotFoundError:
            self.logger.warning(f"原始路径JSON文件不存在: {self.origin_json}")
            return []
        except Exception as e:
            self.logger.warning(f"读取原始路径JSON文件失败: {e}")
            return []
    
    def _read_text_file(self, text_path: str) -> str:
        """读取文本文件内容"""
        try:
            with open(text_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except Exception as e:
            self.logger.error(f"读取文本文件失败 {text_path}: {e}")
            return ""
    
    def _create_prompt(self, text_content: str) -> str:
        """创建Deepseek的prompt"""
        return f"{self.system_prompt}\n\n{text_content}"
    
    def _summarize_single_text(self, task):
        """总结单个文本文件
        返回: (idx, success_bool, message, summary_text)
        """
        idx, text_path, origin_path = task
        
        try:
            # 读取文本内容
            text_content = self._read_text_file(text_path)
            if not text_content.strip():
                return idx, False, "文本内容为空", ""
            
            # 创建prompt
            prompt = self._create_prompt(text_content)
            
            # 调用Deepseek API
            
            client = OpenAI(
                api_key=self.model_api_key,
                base_url="https://api.deepseek.com"
            )
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": text_content}
                ],
                stream=False,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content
            
            # 如果提供了原始路径，在总结开头添加原视频链接
            if origin_path:
                summary = f"[原视频]({origin_path})\n\n{summary}"
            
            return idx, True, "总结成功", summary
            
        except ImportError:
            return idx, False, "请安装 openai 库: pip install openai", ""
        except Exception as e:
            return idx, False, f"API调用失败: {str(e)}", ""
    
    def summarize_texts(self) -> bool:
        """总结所有文本"""
        # 加载文本文件路径列表
        text_paths = self._load_text_file_paths()
        if not text_paths:
            self.logger.error("没有找到需要总结的文本文件")
            return False
        
        # 加载原始路径列表
        origin_paths = self._load_origin_paths()
        
        self.logger.info(f"开始总结 {len(text_paths)} 个文本")
        self.logger.info(f"使用 {self.num_processes} 个进程")
        self.logger.info(f"总结目录: {self.summary_dir}")
        self.logger.info("-" * 60)
        
        start_time = time.time()
        processed = 0
        total = len(text_paths)
        
        # 创建任务列表
        tasks = []
        for idx, text_path in enumerate(text_paths):
            origin_path = origin_paths[idx] if idx < len(origin_paths) else ""
            tasks.append((idx, text_path, origin_path))
        
        # 初始化总结列表
        summaries = [""] * total
        self.summary_file_paths = [""] * total
        
        # 使用进程池
        with ProcessPoolExecutor(max_workers=self.num_processes) as executor:
            # 提交所有任务
            future_to_task = {executor.submit(self._summarize_single_text, task): task for task in tasks}
            
            # 处理结果
            for future in as_completed(future_to_task):
                try:
                    idx, task_success, message, summary_text = future.result()
                except Exception as e:
                    # 捕获子进程异常
                    self.logger.error(f"任务异常: {e}")
                    processed += 1
                    self.failed_count += 1
                    continue

                processed += 1
                
                if task_success:
                    self.success_count += 1
                    summaries[idx] = summary_text
                    status = "✓"
                else:
                    self.failed_count += 1
                    status = "✗"
                
                # 显示进度
                elapsed = time.time() - start_time
                progress = processed / total * 100
                
                log_msg = f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] {status} {idx+1:03d}: {message}"
                self.logger.info(log_msg)
                
                # 每处理10个文件显示一次汇总
                if processed % 10 == 0:
                    summary = f"[进度] {processed}/{total} ({progress:.1f}%) | 成功: {self.success_count} | 失败: {self.failed_count}"
                    self.logger.info(summary)
                    
                    if processed > 0:
                        time_per_file = elapsed / processed
                        remaining = total - processed
                        eta = time_per_file * remaining
                        time_info = f"[时间] 已用: {time.strftime('%H:%M:%S', time.gmtime(elapsed))} | 预计剩余: {time.strftime('%H:%M:%S', time.gmtime(eta))}"
                        self.logger.info(time_info)
        
        # 保存总结到文件
        for idx, summary_text in enumerate(summaries):
            if summary_text.strip():  # 只保存非空总结
                summary_filename = f"{idx+1:03d}.md"
                summary_path = self.summary_dir / summary_filename
                
                try:
                    with open(str(summary_path), 'w', encoding='utf-8') as f:
                        f.write(summary_text)
                    
                    self.summary_file_paths[idx] = str(summary_path)
                    
                except Exception as e:
                    self.logger.error(f"保存总结文件失败 {summary_filename}: {e}")
                    self.summary_file_paths[idx] = ""
        
        # 保存总结文件路径列表到输出JSON
        try:
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(self.summary_file_paths, f, ensure_ascii=False, indent=2)
            self.logger.info(f"总结文件路径列表已保存到: {self.output_json}")
        except Exception as e:
            self.logger.error(f"保存总结文件路径列表失败: {e}")
            return False
        
        # 最终统计
        total_time = time.time() - start_time
        
        self.logger.info("=" * 60)
        self.logger.info("总结完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"总文本数: {self.total_texts}")
        self.logger.info(f"总结成功: {self.success_count}")
        self.logger.info(f"总结失败: {self.failed_count}")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文本/分钟")
        
        return self.success_count > 0
    
    def _setup_logger(self):
        self.logger = logging.getLogger("TextSummarizer")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter('[TextSummarizer] %(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
        
            # 文件handler
            if self.log_file:
                # 使用自定义日志文件
                log_file_path = Path(self.log_file)
                log_file_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用自定义日志文件: {log_file_path}")
            else:
                # 使用默认日志文件
                output_dir = self.summary_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file_path = output_dir / "TextSummarizer.log"
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                self.logger.info(f"使用默认日志文件: {log_file_path}")
            
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('[TextSummarizer] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)