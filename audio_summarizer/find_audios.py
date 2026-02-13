#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频文件查找器
功能：
1. 递归遍历指定目录，查找所有音视频文件
2. 将文件路径列表保存为JSON格式
"""

import os
import json
import time
from pathlib import Path
from typing import List, Set

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
    
    def __init__(self, logger, input_dir: Path, output_dir: Path):
        """
        初始化音频查找器
        
        Args:
            logger: 日志记录器对象
            input_dir: 输入目录路径，递归遍历此目录寻找音视频文件
            output_dir: 输出目录路径，将JSON文件存储在此目录
        """
        self.logger = logger
        self.input_dir = input_dir
        self.output_dir = output_dir
        
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
            output_file = self.output_dir / "audios.json"
            
            # 准备要保存的数据
            data = {
                "metadata": {
                    "input_directory": str(self.input_dir.absolute()),
                    "output_directory": str(self.output_dir.absolute()),
                    "total_files": self.total_files_found,
                    "processed_directories": len(self.processed_dirs),
                    "skipped_directories": len(self.skipped_dirs),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                },
                "audio_files": self.audio_files
            }
            
            # 写入JSON文件
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
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

# 导入time模块（在类定义之后）


def main():
    """命令行入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='查找音视频文件并保存为JSON')
    parser.add_argument('--input', '-i', required=True,
                       help='输入目录路径，递归遍历此目录寻找音视频文件')
    parser.add_argument('--output', '-o', required=True,
                       help='输出目录路径，将JSON文件存储在此目录')
    
    args = parser.parse_args()
    
    try:
        # 创建查找器实例
        finder = AudioFinder(args.input, args.output)
        
        # 执行查找和保存
        if finder.find_and_save():
            print("\n✓ 操作成功完成!")
            stats = finder.get_statistics()
            print(f"   找到文件数: {stats['total_files']}")
            print(f"   处理目录数: {stats['processed_dirs']}")
            print(f"   跳过目录数: {stats['skipped_dirs']}")
        else:
            print("\n✗ 操作失败!")
            
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")

if __name__ == "__main__":
    main()