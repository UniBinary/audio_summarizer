import os
import sys
import oss2
import json
import time
import hashlib
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
    
    def __init__(self, input_dir: Union[str, Path], output_json: Union[str, Path], logger_suffix: str = None, log_file: Union[str, Path] = None, size_limit: int = None, duration_limit: int = None, log_level: int = logging.INFO):
        """
        初始化音视频文件查找器
        
        Args:
            input_dir: 输入目录路径，递归遍历此目录寻找音视频文件
            output_json: 输出的含有音视频文件路径列表的JSON文件路径
            logger_suffix: logger名称后缀，如果给出，则使用f"{logger_suffix}.AVFinder"作为logger名，否则使用"AVFinder"
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
            size_limit: 文件大小限制，单位为MB，若给出则不会将超过限制的音视频加入列表
            duration_limit: 文件时长限制，单位为秒，若给出则不会将超过限制的音视频加入列表
            log_level: 日志级别，默认为DEBUG
        """
        self.input_dir = Path(input_dir)
        self.output_json = Path(output_json)
        self.log_file = Path(log_file) if log_file else None
        self.logger_suffix = logger_suffix
        self.size_limit = size_limit
        self.duration_limit = duration_limit
        self.log_level = log_level
        
        # 设置logger
        self._setup_logger()
        
        # 存储类内数据
        self.audio_files: List[str] = []
        self.processed_dirs: Set[Path] = set()
        self.skipped_dirs: Set[Path] = set()
        self.total_files_found = 0
        self.skipped_by_size = 0
        self.skipped_by_duration = 0
        
        # 验证目录
        self._validate_directories()
    
    def _setup_logger(self):
        logger_name = f"{self.logger_suffix}.AVFinder" if self.logger_suffix else "AVFinder"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(self.log_level)
        # 阻止日志传播到父logger，避免重复记录
        self.logger.propagate = False
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
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
            
            file_handler.setLevel(self.log_level)
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
    
    def _get_file_duration(self, file_path: Path) -> float:
        """
        获取音视频文件的时长（秒）
        
        Args:
            file_path: 文件路径对象
            
        Returns:
            float: 文件时长（秒），如果无法获取则返回None
        """
        try:
            # 使用ffprobe获取时长
            ffprobe_cmd = None
            
            # 尝试不同的ffprobe路径
            possible_paths = [
                Path("ffprobe.exe"),
                Path("ffprobe"),
                Path(r"C:\ffmpeg\bin\ffprobe.exe"),
                Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
                Path(r"D:\ffmpeg\bin\ffprobe.exe"),
            ]
            
            for probe_path in possible_paths:
                if probe_path.exists():
                    ffprobe_cmd = str(probe_path)
                    break
            
            if not ffprobe_cmd:
                self.logger.debug(f"未找到ffprobe，无法获取文件时长: {file_path}")
                return None
            
            cmd = [
                ffprobe_cmd,
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
    
    def _check_file_limits(self, file_path: Path) -> bool:
        """
        检查文件是否超过大小或时长限制
        
        Args:
            file_path: 文件路径对象
            
        Returns:
            bool: 如果文件符合限制返回True，否则返回False
        """
        # 检查文件大小限制
        if self.size_limit is not None:
            try:
                file_size_mb = file_path.stat().st_size / (1024 * 1024)  # 转换为MB
                if file_size_mb > self.size_limit:
                    self.logger.debug(f"跳过文件（大小超出限制）: {file_path} ({file_size_mb:.2f} MB > {self.size_limit} MB)")
                    self.skipped_by_size += 1
                    return False
            except Exception as e:
                self.logger.debug(f"获取文件大小失败 {file_path}: {e}")
        
        # 检查文件时长限制
        if self.duration_limit is not None:
            try:
                duration = self._get_file_duration(file_path)
                if duration is not None and duration > self.duration_limit:
                    self.logger.debug(f"跳过文件（时长超出限制）: {file_path} ({duration:.2f} 秒 > {self.duration_limit} 秒)")
                    self.skipped_by_duration += 1
                    return False
            except Exception as e:
                self.logger.debug(f"检查文件时长限制失败 {file_path}: {e}")
        
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
                            # 检查文件大小和时长限制
                            if not self._check_file_limits(item):
                                continue
                            
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
        self.skipped_by_size = 0
        self.skipped_by_duration = 0
        
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
        
        # 显示限制相关的统计信息
        if self.size_limit is not None:
            self.logger.info(f"文件大小限制: {self.size_limit} MB")
            self.logger.info(f"因大小限制跳过的文件数: {self.skipped_by_size}")
        
        if self.duration_limit is not None:
            self.logger.info(f"文件时长限制: {self.duration_limit} 秒")
            self.logger.info(f"因时长限制跳过的文件数: {self.skipped_by_duration}")
        
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
        stats = {
            "total_files": self.total_files_found,
            "processed_dirs": len(self.processed_dirs),
            "skipped_dirs": len(self.skipped_dirs),
            "audio_files": self.audio_files[:10] if self.audio_files else []  # 只返回前10个作为示例
        }
        
        # 添加限制相关的统计信息
        if self.size_limit is not None:
            stats["size_limit_mb"] = self.size_limit
            stats["skipped_by_size"] = self.skipped_by_size
        
        if self.duration_limit is not None:
            stats["duration_limit_seconds"] = self.duration_limit
            stats["skipped_by_duration"] = self.skipped_by_duration
        
        return stats



class AudioExtractor:
    """提取音频类"""
    
    AUDIO_EXTENSIONS = {
        # 音频格式
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'
    }

    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], audio_dir: Union[str, Path], 
                 ffmpeg_path: Union[str, Path], ffprobe_path: Union[str, Path], num_processes: int = 1, logger_suffix: str = None, 
                 log_file: Union[str, Path] = None, log_level: int = logging.INFO):
        """
        初始化音频提取器
        
        Args:
            input_json: 输入的含有音视频文件路径列表的JSON文件路径
            output_json: 输出的包含原有的音频文件和从视频中提取的音频文件的路径列表的JSON文件路径
            audio_dir: 提取后的音频存放目录路径
            ffmpeg_path: ffmpeg可执行文件路径
            ffprobe_path: ffprobe可执行文件路径
            num_processes: 并行进程数，默认为1
            logger_suffix: logger名称后缀，如果给出，则使用f"{logger_suffix}.AudioExtractor"作为logger名，否则使用"AudioExtractor"
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
            log_level: 日志级别，默认为DEBUG"""
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.audio_dir = Path(audio_dir)
        self.ffmpeg_path = Path(ffmpeg_path)
        self.ffprobe_path = Path(ffprobe_path)
        self.num_processes = num_processes
        self.log_file = Path(log_file) if log_file else None
        self.logger_suffix = logger_suffix
        
        # 设置logger
        self.log_level = log_level
        self._setup_logger()
        
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
        logger_name = f"{self.logger_suffix}.AudioExtractor" if self.logger_suffix else "AudioExtractor"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(self.log_level)
        # 阻止日志传播到父logger，避免重复记录
        self.logger.propagate = False
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
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
            
            file_handler.setLevel(self.log_level)
            file_formatter = logging.Formatter('[AudioExtractor] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
    
    def _load_video_list(self):
        """从JSON文件加载视频列表"""
        self.logger.info(f"读取视频列表: {self.input_json}")
        try:
            with open(str(self.input_json), 'r', encoding='utf-8-sig') as f:
                self.video_paths = json.load(f)
            
            # 检查并过滤空字符串
            filtered_paths = []
            for i, path in enumerate(self.video_paths):
                if not path or str(path).strip() == "":
                    self.logger.warning(f"检测到空字符串路径，跳过索引 {i}")
                else:
                    filtered_paths.append(path)
            
            self.video_paths = filtered_paths
            self.logger.info(f"加载了 {len(self.video_paths)} 个有效路径（跳过了 {len(self.video_paths) - len(filtered_paths)} 个空字符串）")
            
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
            self.logger.debug("无法获取时长，无法验证音频正确性")
            return False  # 无法验证，假设不正确

        # 检查时长差异（允许5秒差异）
        duration_diff = abs(video_duration - audio_duration)
        is_correct = duration_diff <= 5
        
        if is_correct:
            self.logger.debug(f"音频文件验证通过，时长差异: {duration_diff:.2f} 秒")
        else:
            self.logger.debug(f"音频文件验证失败，时长差异: {duration_diff:.2f} 秒 > 5秒")
        
        return is_correct
    
    def _extract_audio(self, task):
        """提取单个音频文件
        返回: (idx, success_bool, message, audio_path_str, size_bytes, duration_sec)
        """
        # 在子进程中重新配置logger
        if not self.logger.handlers:
            self._setup_logger()
        
        idx, video_path = task
        
        # 添加测试debug日志
        self.logger.debug(f"开始提取音频: {video_path}")
        
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
            self.logger.debug(f"音频文件已存在: {audio_path}")
            audio_duration = self._get_duration(audio_path)
            if audio_duration is not None and self._check_audio_correct(input_path, audio_path):
                self.logger.debug(f"音频文件验证通过，跳过提取: {audio_path}")
                return idx, True, "已存在且正确（时长差异<5秒）", str(audio_path), audio_path.stat().st_size, audio_duration
            else:
                # 音频不正确或无法验证，删除并重新提取
                self.logger.debug(f"音频文件验证失败或无法验证，删除并重新提取: {audio_path}")
                try:
                    audio_path.unlink()
                    self.logger.debug(f"删除不正确的音频文件: {audio_path}")
                except Exception as e:
                    self.logger.debug(f"删除文件失败 {audio_path}: {e}")
                    return idx, False, f"无法删除不正确的音频文件: {e}", "", 0, 0
        
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
                    
                    # 找出哪些文件是原始音频文件（不需要在音频目录中）
                    original_audio_numbers = set()
                    for idx, video_path in enumerate(self.video_paths):
                        video_path_obj = Path(video_path)
                        if video_path_obj.suffix.lower() in self.AUDIO_EXTENSIONS:
                            original_audio_numbers.add(idx + 1)  # 索引 +1 对应编号
                    
                    # 从缺失编号中排除原始音频文件对应的编号
                    missing = [num for num in missing if num not in original_audio_numbers]
                    
                    if missing:
                        self.logger.warning(f"缺失编号: {len(missing)} 个")
                        for num in missing[:10]:
                            self.logger.warning(f"  {num:03d}")
                        if len(missing) > 10:
                            self.logger.warning(f"  ... 还有 {len(missing)-10} 个")
                    else:
                        # 如果所有缺失的编号都是原始音频文件，显示信息而不是警告
                        if original_audio_numbers:
                            self.logger.info(f"✓ 所有编号连续完整（{len(original_audio_numbers)} 个原始音频文件未复制到音频目录）")
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
                    elif "已存在且正确" in message:
                        self.skipped_count += 1  # 已存在的正确文件也算跳过
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
        
        # 将处理结果写回输出 JSON（保持索引一致）
        try:
            # 创建输出列表
            output_list = []
            for idx in range(len(self.video_paths)):
                if idx in extracted_map:
                    # 提取成功，使用音频路径
                    output_list.append(extracted_map[idx])
                else:
                    # 提取失败或跳过，使用空字符串
                    output_list.append("")
            
            # 写回输出JSON
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(output_list, f, ensure_ascii=False, indent=2)
                self.logger.info(f"已将处理结果写入 {self.output_json}")
                self.logger.info(f"  - 成功提取: {len(extracted_map)} 个文件")
                self.logger.info(f"  - 失败/跳过: {len(self.video_paths) - len(extracted_map)} 个文件（输出为空字符串）")
        except Exception as e:
            self.logger.error(f"写入输出 JSON 失败: {e}")
            return False
        
        # 最终统计
        total_time = time.time() - start_time
        
        self.logger.info("=" * 60)
        self.logger.info("处理完成!")
        self.logger.info("=" * 60)
        self.logger.info(f"总时长: {self.total_duration/3600:.2f} 小时")
        self.logger.info(f"总文件数: {self.total_files}")
        self.logger.info(f"成功提取: {self.success_count}")
        self.logger.info(f"处理失败: {self.failed_count}")
        self.logger.info(f"跳过文件: {self.skipped_count} (包含已存在的正确文件和原始音频文件)")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        self.logger.info(f"总大小: {self.total_size/1024/1024/1024:.2f} GB")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文件/分钟")
        
        # 检查输出目录内容
        self._check_output_directory()
        
        # 只要没有发生完全失败（如加载列表失败、写入JSON失败），就返回True
        # 即使有文件处理失败，也返回True，因为失败的文件已在输出JSON中留空
        # 后续模块会跳过空字符串，继续处理其他文件
        return True



class OSSUploader:
    """上传音频到OSS类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], bucket_name: str, 
                 bucket_endpoint: str, access_key_id: str, access_key_secret: str, 
                 num_processes: int = 1, skip_exists: bool = False,
                 logger_suffix: str = None, log_file: Union[str, Path] = None, log_level: int = logging.INFO):
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
            skip_exists: 如果设为True，则跳过OSS上已有的文件
            logger_suffix: logger名称后缀，如果给出，则使用f"{logger_suffix}.OSSUploader"作为logger名，否则使用"OSSUploader"
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
            log_level: 日志级别，默认为DEBUG"""
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.bucket_name = bucket_name
        self.bucket_endpoint = bucket_endpoint
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.num_processes = num_processes
        self.skip_exists = skip_exists
        self.log_file = Path(log_file) if log_file else None
        self.logger_suffix = logger_suffix
        
        # 设置logger
        self.log_level = log_level
        self._setup_logger()
        
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
        self.skipped_count = 0
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
            
            # 检查并过滤空字符串
            filtered_list = []
            for i, file_path in enumerate(file_list):
                if not file_path or str(file_path).strip() == "":
                    self.logger.warning(f"检测到空字符串文件路径，跳过索引 {i}")
                else:
                    filtered_list.append(file_path)
            
            self.total_files = len(filtered_list)
            self.logger.info(f"找到 {self.total_files} 个有效文件需要上传（跳过了 {len(file_list) - len(filtered_list)} 个空字符串）")
            return filtered_list
            
        except FileNotFoundError:
            self.logger.error(f"输入JSON文件不存在: {self.input_json}")
            return []
        except Exception as e:
            self.logger.error(f"读取JSON文件失败: {e}")
            return []
    
    def _check_file_match(self, local_path: Path, object_name: str) -> bool:
        """
        检查本地文件与OSS上的文件是否匹配
        
        Args:
            local_path: 本地文件路径
            object_name: OSS对象名
            
        Returns:
            bool: 如果文件匹配返回True，否则返回False
        """
        try:
            # 获取OSS文件信息
            oss_meta = self.bucket.get_object_meta(object_name)
            # 检查ETag（通常是MD5哈希值）
            oss_etag = oss_meta.headers.get('ETag', '').strip('"')

            if oss_etag:
                # 计算本地文件的MD5哈希值
                md5_hash = hashlib.md5()
                with open(local_path, 'rb') as f:
                    # 分块读取大文件
                    for chunk in iter(lambda: f.read(8192), b''):
                        md5_hash.update(chunk)
                local_md5 = md5_hash.hexdigest()
                
                # 比较哈希值（忽略大小写）
                if local_md5.lower() == oss_etag.lower():
                    self.logger.debug(f"文件哈希值匹配: {object_name} (MD5: {local_md5})")
                    return True
                else:
                    # 哈希值不匹配
                    self.logger.debug(f"文件哈希值不匹配")
                    return False
            else:
                self.logger.warning("无法获取文件哈希值，认为不匹配")
                return False
            
        except Exception as e:
            self.logger.debug(f"检查文件匹配失败 {object_name}: {e}")
            return False
    
    def _upload_single_file(self, task):
        """上传单个文件到OSS
        返回: (idx, success_bool, message, url)
        """
        idx, file_path = task
        file_path_obj = Path(file_path)
        
        # 生成OSS对象名: oss://audios/<索引+1，补齐三位数>.<后缀名>
        extension = file_path_obj.suffix.lower()
        object_name = f"audios/{idx+1:03d}{extension}"
        
        # 在子进程中重新配置logger
        if not self.logger.handlers:
            self._setup_logger()
        
        try:
            # 检查文件是否存在
            if not file_path_obj.exists():
                return idx, False, "本地文件不存在", ""
            
            # 如果skip_exists为True，检查OSS上是否已存在该文件
            if self.skip_exists:
                try:
                    # 检查对象是否存在
                    exists = self.bucket.object_exists(object_name)
                    self.logger.debug(f"检查OSS文件: {object_name}, 存在: {exists}")
                    if exists:
                        if self._check_file_match(file_path_obj, object_name):
                            # 文件匹配，生成URL并跳过上传
                            self.logger.debug(f"文件匹配，跳过上传: {object_name}")
                            url = self.bucket.sign_url('GET', object_name, 86400)
                            return idx, True, "文件已存在且匹配，跳过上传", url
                        else:
                            # 文件不匹配，重新上传
                            self.logger.info(f"文件 {object_name} 存在但不匹配，重新上传")
                except Exception as e:
                    self.logger.debug(f"检查OSS文件存在性失败 {object_name}: {e}")
                    # 如果检查失败，继续正常上传流程
            
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
                    if "跳过上传" in message:
                        self.skipped_count += 1
                        status = "↻"      # 跳过上传
                    else:
                        self.success_count += 1
                        status = "✓"      # 实际上传成功
                    self.uploaded_urls[idx] = url
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
                    summary = f"[进度] {processed}/{total} ({progress:.1f}%) | 成功: {self.success_count} | 跳过: {self.skipped_count} | 失败: {self.failed_count}"
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
        self.logger.info(f"跳过上传: {self.skipped_count}")
        self.logger.info(f"上传失败: {self.failed_count}")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文件/分钟")
        
        # 只要没有发生完全失败（如加载列表失败、保存JSON失败），就返回True
        # 即使所有文件上传失败，也返回True，因为失败的文件已在输出JSON中留空
        # 后续模块会跳过空字符串，继续处理其他文件
        return True
    
    def _setup_logger(self):
        logger_name = f"{self.logger_suffix}.OSSUploader" if self.logger_suffix else "OSSUploader"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(self.log_level)
        # 阻止日志传播到父logger，避免重复记录
        self.logger.propagate = False
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
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
            
            file_handler.setLevel(self.log_level)
            file_formatter = logging.Formatter('[OSSUploader] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)



class AudioTranscriber:
    """音频转文字类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], text_dir: Union[str, Path], 
                 model_api_key: str, num_processes: int = 1, logger_suffix: str = None, log_file: Union[str, Path] = None, log_level: int = logging.INFO):
        """
        初始化音频转录器
        
        Args:
            input_json: 输入的包含所有音频文件的公网URL的JSON文件路径
            output_json: 输出的包含所有音频转写生成的文字文件的路径的JSON文件路径
            text_dir: 存放音频转写生成的文字文件的文件夹
            model_api_key: Fun-ASR模型API key
            num_processes: 并行进程数，默认为1
            logger_suffix: logger名称后缀，如果给出，则使用f"{logger_suffix}.AudioTranscriber"作为logger名，否则使用"AudioTranscriber"
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
            log_level: 日志级别，默认为DEBUG"""
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.text_dir = Path(text_dir)
        self.model_api_key = model_api_key
        self.num_processes = num_processes
        self.log_file = Path(log_file) if log_file else None
        self.logger_suffix = logger_suffix
        
        # 设置logger
        self.log_level = log_level
        self._setup_logger()
        
        # 初始化统计信息
        self.total_urls = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0  # 添加跳过计数器
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
            
            # 检查并过滤空字符串
            filtered_list = []
            for i, url in enumerate(url_list):
                if not url or str(url).strip() == "":
                    self.logger.warning(f"检测到空字符串URL，跳过索引 {i}")
                else:
                    filtered_list.append(url)
            
            self.total_urls = len(filtered_list)
            self.logger.info(f"找到 {self.total_urls} 个有效URL需要转录（跳过了 {len(url_list) - len(filtered_list)} 个空字符串）")
            return filtered_list
            
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
        """转录一个批次的音频URL，通过URL匹配确保顺序正确"""
        # 在子进程中重新配置logger
        if not self.logger.handlers:
            self._setup_logger()
        
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
            
            # 初始化结果列表，长度与batch_urls相同
            results = [""] * len(batch_urls)
            
            if transcription_response.status_code == HTTPStatus.OK:
                # 调试：打印API返回的数据结构前几个字符
                self.logger.debug(f"批次 {batch_index} API返回结果数: {len(transcription_response.output['results'])}")
                
                for transcription in transcription_response.output['results']:
                    # 调试：查看转录结果的结构
                    transcription_str = str(transcription)
                    if len(transcription_str) > 200:
                        transcription_str = transcription_str[:200] + "..."
                    self.logger.debug(f"转录结果结构: {transcription_str}")
                    
                    if transcription['subtask_status'] == 'SUCCEEDED':
                        url = transcription['transcription_url']
                        result_data = json.loads(request.urlopen(url).read().decode('utf8'))
                        
                        # 格式化转录结果
                        result_str = self._format_transcription_result(result_data)
                        
                        # 关键：通过URL匹配找到正确的索引
                        matched_index = self._match_transcription_to_url(transcription, batch_urls, batch_index)
                        
                        if 0 <= matched_index < len(batch_urls):
                            results[matched_index] = result_str
                            self.logger.debug(f"匹配成功: 结果放入索引 {matched_index} (URL: {batch_urls[matched_index][:50]}...)")
                        else:
                            # 如果无法匹配，记录警告并按顺序放入第一个空位
                            self.logger.warning(f"批次 {batch_index}: 无法匹配转录结果到原始URL")
                            for i in range(len(results)):
                                if results[i] == "":
                                    results[i] = result_str
                                    self.logger.warning(f"  结果放入索引 {i} (按顺序)")
                                    break
                    else:
                        self.logger.error(f'转录失败: {transcription}')
                        # 失败时保持空字符串
            else:
                self.logger.error(f'Fun-ASR API错误: {transcription_response.output.message}')
                # 返回空字符串列表
                results = [""] * len(batch_urls)
            
            # 检查是否有未匹配的结果
            empty_count = sum(1 for r in results if r == "")
            if empty_count > 0:
                self.logger.warning(f"批次 {batch_index}: 有 {empty_count} 个结果未匹配到URL")
            
            return results
            
        except ImportError:
            self.logger.error("请安装 dashscope 库: pip install dashscope")
            raise
        except Exception as e:
            self.logger.error(f"转录批次 {batch_index} 失败: {e}")
            # 返回空字符串列表
            return [""] * len(batch_urls)
    
    def _match_transcription_to_url(self, transcription: dict, batch_urls: List[str], batch_index: int) -> int:
        """
        将转录结果匹配到原始URL的索引
        
        Args:
            transcription: API返回的转录结果
            batch_urls: 批次的URL列表
            batch_index: 批次索引
            
        Returns:
            int: 匹配的索引，如果无法匹配返回-1
        """
        # 首先，记录transcription的所有键，以便调试
        self.logger.debug(f"批次 {batch_index}: transcription keys: {list(transcription.keys())}")
        
        # 方法1: 检查transcription中是否包含原始URL信息
        # Fun-ASR API可能返回file_url字段
        if 'file_url' in transcription:
            file_url = transcription['file_url']
            self.logger.debug(f"批次 {batch_index}: 找到file_url: {file_url[:100]}...")
            
            # 尝试匹配URL
            for i, batch_url in enumerate(batch_urls):
                # 简化URL匹配：检查URL的关键部分
                # 提取文件名部分进行匹配
                batch_filename = self._extract_filename_from_url(batch_url)
                transcription_filename = self._extract_filename_from_url(file_url)
                
                self.logger.debug(f"批次 {batch_index}: 比较 batch_filename='{batch_filename}' vs transcription_filename='{transcription_filename}'")
                
                if batch_filename and transcription_filename and batch_filename == transcription_filename:
                    self.logger.debug(f"批次 {batch_index}: 通过文件名匹配成功: 索引 {i}")
                    return i
                
                # 或者直接检查URL是否包含对方
                if batch_url in file_url or file_url in batch_url:
                    self.logger.debug(f"批次 {batch_index}: 通过URL包含关系匹配成功: 索引 {i}")
                    return i
        
        # 方法2: 检查是否有index字段
        if 'index' in transcription:
            idx = transcription['index']
            self.logger.debug(f"批次 {batch_index}: 找到index: {idx}")
            if 0 <= idx < len(batch_urls):
                self.logger.debug(f"批次 {batch_index}: 通过index匹配成功: 索引 {idx}")
                return idx
        
        # 方法3: 检查是否有其他可能的字段
        # 尝试所有字符串字段，看是否包含URL信息
        for key, value in transcription.items():
            if isinstance(value, str) and len(value) > 10:
                # 检查是否包含batch_urls中的任何URL
                for i, batch_url in enumerate(batch_urls):
                    # 提取batch_url的基本部分（去除查询参数）
                    batch_url_simple = batch_url.split('?')[0]
                    if batch_url_simple in value:
                        self.logger.debug(f"批次 {batch_index}: 通过字段 '{key}' 匹配成功: 索引 {i}")
                        return i
        
        # 方法4: 如果以上方法都失败，记录详细的调试信息
        self.logger.warning(f"批次 {batch_index}: 无法通过URL匹配确定索引")
        self.logger.warning(f"批次 {batch_index}: transcription内容: {str(transcription)[:500]}")
        
        # 返回-1表示无法匹配，调用者将按顺序处理
        return -1
    
    def _extract_filename_from_url(self, url: str) -> str:
        """从URL中提取文件名"""
        try:
            # 移除查询参数
            url_without_query = url.split('?')[0]
            # 获取最后一部分
            filename = url_without_query.split('/')[-1]
            # URL解码（如果包含%编码）
            import urllib.parse
            filename = urllib.parse.unquote(filename)
            return filename
        except:
            return ""
    
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
        
        # 过滤掉已有有效文本文件的URL
        filtered_urls = []
        skipped_indices = []
        
        for idx, url in enumerate(url_list):
            text_filename = f"{idx+1:03d}.txt"
            text_path = self.text_dir / text_filename
            
            if text_path.exists():
                try:
                    with open(str(text_path), 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    
                    # 如果文件已存在且内容非空，跳过转录
                    if existing_content.strip():
                        self.logger.debug(f"文本文件已存在且内容有效，跳过转录: {text_path}")
                        skipped_indices.append(idx)
                        continue
                    else:
                        self.logger.debug(f"文本文件已存在但内容为空，需要重新转录: {text_path}")
                except Exception as e:
                    self.logger.debug(f"读取现有文本文件失败 {text_path}: {e}")
                    # 如果读取失败，继续转录
            
            filtered_urls.append((idx, url))  # 保存原始索引和URL
        
        self.logger.info(f"原始URL数: {len(url_list)}")
        self.logger.info(f"需要转录的URL数: {len(filtered_urls)}")
        self.logger.info(f"跳过的URL数: {len(skipped_indices)} (文件已存在且内容有效)")
        
        if not filtered_urls:
            self.logger.info("所有音频都已转录完成，无需处理")
            # 仍然需要生成输出JSON
            self._generate_output_json(url_list, skipped_indices)
            return True
        
        # 提取需要转录的URL
        urls_to_transcribe = [url for _, url in filtered_urls]
        original_indices = [idx for idx, _ in filtered_urls]
        
        # 将URL分成批次
        url_batches = self._split_urls_into_batches(urls_to_transcribe)
        
        self.logger.info(f"开始转录 {len(urls_to_transcribe)} 个音频")
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
        
        # 将回传字典转为列表并展开（只包含实际转录的结果）
        transcribed_results = []
        for batch_index in sorted(result_dict.keys()):
            transcribed_results.extend(result_dict[batch_index])
        
        # 现在我们需要将转录结果映射回原始索引
        # 创建一个字典来映射原始索引到转录结果
        index_to_result = {}
        for i, (original_idx, url) in enumerate(filtered_urls):
            if i < len(transcribed_results):
                index_to_result[original_idx] = transcribed_results[i]
            else:
                index_to_result[original_idx] = ""  # 如果结果不够，使用空字符串
        
        # 对于跳过的索引，我们需要从文件中读取内容
        for idx in skipped_indices:
            text_filename = f"{idx+1:03d}.txt"
            text_path = self.text_dir / text_filename
            try:
                with open(str(text_path), 'r', encoding='utf-8') as f:
                    existing_content = f.read()
                index_to_result[idx] = existing_content
            except Exception as e:
                self.logger.error(f"读取跳过的文件失败 {text_path}: {e}")
                index_to_result[idx] = ""
        
        # 保存转录结果到文件并生成文件路径列表
        self.text_file_paths = [""] * len(url_list)  # 初始化与原始URL列表相同长度的列表
        self.skipped_count = len(skipped_indices)  # 设置跳过计数器
        
        # 处理所有索引（包括跳过的和实际转录的）
        for idx in range(len(url_list)):
            text_filename = f"{idx+1:03d}.txt"
            text_path = self.text_dir / text_filename
            
            # 如果这个索引是跳过的，文件路径已经存在
            if idx in skipped_indices:
                self.text_file_paths[idx] = str(text_path)
                continue
            
            # 获取这个索引的转录结果
            result_text = index_to_result.get(idx, "")
            
            # 如果转录结果为空，添加空字符串到输出列表
            if not result_text.strip():
                self.text_file_paths[idx] = ""
                self.failed_count += 1
                continue
            
            # 保存转录结果到文件
            try:
                with open(str(text_path), 'w', encoding='utf-8') as f:
                    f.write(result_text)
                
                self.text_file_paths[idx] = str(text_path)
                self.success_count += 1
                    
            except Exception as e:
                self.logger.error(f"保存文本文件失败 {text_filename}: {e}")
                self.text_file_paths[idx] = ""
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
        self.logger.info(f"跳过转录: {self.skipped_count} (文件已存在且内容有效)")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if self.total_urls > 0:
            self.logger.info(f"平均速度: {self.total_urls/(total_time/60):.1f} 音频/分钟")
        
        # 只要没有发生完全失败（如加载列表失败、保存JSON失败），就返回True
        # 即使所有文件转录失败，也返回True，因为失败的文件已在输出JSON中留空
        # 后续模块会跳过空字符串，继续处理其他文件
        return True
    
    def _generate_output_json(self, url_list: List[str], skipped_indices: List[int]) -> bool:
        """
        生成输出JSON文件（当所有文件都已跳过时使用）
        
        Args:
            url_list: 原始URL列表
            skipped_indices: 跳过的索引列表
            
        Returns:
            bool: 操作成功返回True，否则返回False
        """
        try:
            # 生成文件路径列表
            text_file_paths = [""] * len(url_list)
            
            for idx in range(len(url_list)):
                text_filename = f"{idx+1:03d}.txt"
                text_path = self.text_dir / text_filename
                
                # 如果这个索引是跳过的，添加文件路径
                if idx in skipped_indices:
                    text_file_paths[idx] = str(text_path)
                else:
                    # 对于非跳过的索引，理论上不应该发生这种情况
                    # 但如果发生，使用空字符串
                    text_file_paths[idx] = ""
            
            # 保存文本文件路径列表到输出JSON
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(text_file_paths, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"文本文件路径列表已保存到: {self.output_json}")
            self.logger.info(f"所有 {len(skipped_indices)} 个文件都已存在，跳过转录")
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成输出JSON失败: {e}")
            return False
    
    def _setup_logger(self):
        logger_name = f"{self.logger_suffix}.AudioTranscriber" if self.logger_suffix else "AudioTranscriber"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(self.log_level)
        # 阻止日志传播到父logger，避免重复记录
        self.logger.propagate = False
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
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
            
            file_handler.setLevel(self.log_level)  # 文件记录指定级别及以上
            file_formatter = logging.Formatter('[AudioTranscriber] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)



class TextSummarizer:
    """总结文字类"""
    
    def __init__(self, input_json: Union[str, Path], output_json: Union[str, Path], summary_dir: Union[str, Path], 
                 model_api_key: str, num_processes: int = 1, origin_json: Union[str, Path] = None, logger_suffix: str = None, 
                 log_file: Union[str, Path] = None, log_level: int = logging.INFO):
        """
        初始化文本总结器
        
        Args:
            input_json: 输入的包含所有音频转写生成的文字文件的路径的JSON文件路径
            output_json: 输出的包含所有Deepseek生成的文字总结文件的路径的JSON文件路径
            summary_dir: 存放Deepseek生成的文字总结的文件夹
            model_api_key: Deepseek模型API key
            num_processes: 并行进程数，默认为1
            origin_json: 包含每个文本文件对应的原视频路径的列表的JSON文件路径，若为空则不在生成的总结头部添加原视频路径
            logger_suffix: logger名称后缀，如果给出，则使用f"{logger_suffix}.TextSummarizer"作为logger名，否则使用"TextSummarizer"
            log_file: 自定义日志文件路径，若不为None则将日志输出到此文件
            log_level: 日志级别，默认为DEBUG"""
        self.input_json = Path(input_json)
        self.output_json = Path(output_json)
        self.summary_dir = Path(summary_dir)
        self.model_api_key = model_api_key
        self.num_processes = num_processes
        self.origin_json = Path(origin_json) if origin_json else None
        self.log_file = Path(log_file) if log_file else None
        self.logger_suffix = logger_suffix
        
        # 设置logger
        self.log_level = log_level
        self._setup_logger()
        
        # 初始化统计信息
        self.total_texts = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0  # 添加跳过计数器
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
            
            # 检查并过滤空字符串
            filtered_paths = []
            for i, text_path in enumerate(text_paths):
                if not text_path or str(text_path).strip() == "":
                    self.logger.warning(f"检测到空字符串文本路径，跳过索引 {i}")
                else:
                    filtered_paths.append(text_path)
            
            self.total_texts = len(filtered_paths)
            self.logger.info(f"找到 {self.total_texts} 个有效文本文件需要总结（跳过了 {len(text_paths) - len(filtered_paths)} 个空字符串）")
            return filtered_paths
            
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
        # 在子进程中重新配置logger
        if not self.logger.handlers:
            self._setup_logger()
        
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
        
        # 过滤掉已有有效总结文件的文本
        filtered_tasks = []
        skipped_indices = []
        
        for idx, text_path in enumerate(text_paths):
            summary_filename = f"{idx+1:03d}.md"
            summary_path = self.summary_dir / summary_filename
            origin_path = origin_paths[idx] if idx < len(origin_paths) else ""
            
            if summary_path.exists():
                try:
                    with open(str(summary_path), 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    
                    # 如果总结文件已存在且内容非空，跳过总结
                    if existing_content.strip():
                        self.logger.debug(f"总结文件已存在且内容有效，跳过总结: {summary_path}")
                        skipped_indices.append(idx)
                        continue
                    else:
                        self.logger.debug(f"总结文件已存在但内容为空，需要重新总结: {summary_path}")
                except Exception as e:
                    self.logger.debug(f"读取现有总结文件失败 {summary_path}: {e}")
                    # 如果读取失败，继续总结
            
            filtered_tasks.append((idx, text_path, origin_path))
        
        self.logger.info(f"原始文本数: {len(text_paths)}")
        self.logger.info(f"需要总结的文本数: {len(filtered_tasks)}")
        self.logger.info(f"跳过的文本数: {len(skipped_indices)} (总结文件已存在且内容有效)")
        
        if not filtered_tasks:
            self.logger.info("所有文本都已总结完成，无需处理")
            # 仍然需要生成输出JSON
            return self._generate_output_json(text_paths, skipped_indices)
        
        self.logger.info(f"开始总结 {len(filtered_tasks)} 个文本")
        self.logger.info(f"使用 {self.num_processes} 个进程")
        self.logger.info(f"总结目录: {self.summary_dir}")
        self.logger.info("-" * 60)
        
        start_time = time.time()
        processed = 0
        total = len(filtered_tasks)
        
        # 初始化总结列表（只针对需要总结的文本）
        summaries = [""] * len(text_paths)  # 保持原始长度
        self.summary_file_paths = [""] * len(text_paths)  # 保持原始长度
        self.skipped_count = len(skipped_indices)  # 设置跳过计数器
        
        # 使用进程池
        with ProcessPoolExecutor(max_workers=self.num_processes) as executor:
            # 提交过滤后的任务
            future_to_task = {executor.submit(self._summarize_single_text, task): task for task in filtered_tasks}
            
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
                    summaries[idx] = summary_text  # 使用原始索引
                    status = "✓"
                else:
                    self.failed_count += 1
                    status = "✗"
                
                # 显示进度（使用原始索引+1显示）
                elapsed = time.time() - start_time
                progress = processed / total * 100
                
                log_msg = f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] {status} {idx+1:03d}: {message}"
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
        
        # 保存总结到文件并处理跳过的文件
        for idx in range(len(text_paths)):
            summary_filename = f"{idx+1:03d}.md"
            summary_path = self.summary_dir / summary_filename
            
            # 如果这个索引是跳过的，文件路径已经存在
            if idx in skipped_indices:
                self.summary_file_paths[idx] = str(summary_path)
                continue
            
            # 获取这个索引的总结文本
            summary_text = summaries[idx]
            
            # 如果总结文本为空，添加空字符串到输出列表
            if not summary_text.strip():
                self.summary_file_paths[idx] = ""
                # 注意：这里不增加failed_count，因为已经在任务处理中增加了
                continue
            
            # 保存总结到文件
            try:
                with open(str(summary_path), 'w', encoding='utf-8') as f:
                    f.write(summary_text)
                
                self.summary_file_paths[idx] = str(summary_path)
                
            except Exception as e:
                self.logger.error(f"保存总结文件失败 {summary_filename}: {e}")
                self.summary_file_paths[idx] = ""
                # 注意：这里不增加failed_count，因为已经在任务处理中增加了
        
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
        self.logger.info(f"跳过总结: {self.skipped_count} (文件已存在且内容有效)")
        self.logger.info(f"总耗时: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
        
        if processed > 0:
            self.logger.info(f"平均速度: {processed/(total_time/60):.1f} 文本/分钟")
        
        # 只要没有发生完全失败（如加载列表失败、保存JSON失败），就返回True
        # 即使所有文件总结失败，也返回True，因为失败的文件已在输出JSON中留空
        return True
    
    def _generate_output_json(self, text_paths: List[str], skipped_indices: List[int]) -> bool:
        """
        生成输出JSON文件（当所有文件都已跳过时使用）
        
        Args:
            text_paths: 原始文本文件路径列表
            skipped_indices: 跳过的索引列表
            
        Returns:
            bool: 操作成功返回True，否则返回False
        """
        try:
            # 生成文件路径列表
            summary_file_paths = [""] * len(text_paths)
            
            for idx in range(len(text_paths)):
                summary_filename = f"{idx+1:03d}.md"
                summary_path = self.summary_dir / summary_filename
                
                # 如果这个索引是跳过的，添加文件路径
                if idx in skipped_indices:
                    summary_file_paths[idx] = str(summary_path)
                else:
                    # 对于非跳过的索引，理论上不应该发生这种情况
                    # 但如果发生，使用空字符串
                    summary_file_paths[idx] = ""
            
            # 保存总结文件路径列表到输出JSON
            with open(str(self.output_json), 'w', encoding='utf-8') as f:
                json.dump(summary_file_paths, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"总结文件路径列表已保存到: {self.output_json}")
            self.logger.info(f"所有 {len(skipped_indices)} 个文件都已存在，跳过总结")
            
            # 更新统计信息
            self.skipped_count = len(skipped_indices)
            self.summary_file_paths = summary_file_paths
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成输出JSON失败: {e}")
            return False
    
    def _setup_logger(self):
        logger_name = f"{self.logger_suffix}.TextSummarizer" if self.logger_suffix else "TextSummarizer"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(self.log_level)
        # 阻止日志传播到父logger，避免重复记录
        self.logger.propagate = False
        
        if not self.logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
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
            
            file_handler.setLevel(self.log_level)
            file_formatter = logging.Formatter('[TextSummarizer] %(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
