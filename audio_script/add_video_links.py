#!/usr/bin/env python3
"""
为Markdown总结文件添加原视频文件路径链接
"""

import os
import json
import re
import argparse
import logging
from pathlib import Path
from typing import List, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_videos_json(videos_json_path: str) -> List[str]:
    """加载videos.json文件"""
    try:
        with open(videos_json_path, 'r', encoding='utf-8') as f:
            videos = json.load(f)
        logger.info(f"成功加载 {len(videos)} 个视频路径")
        return videos
    except FileNotFoundError:
        logger.error(f"videos.json文件不存在: {videos_json_path}")
        raise
    except json.JSONDecodeError:
        logger.error(f"videos.json文件格式错误: {videos_json_path}")
        raise

def extract_file_number(filename: str) -> Optional[int]:
    """从文件名中提取编号"""
    # 匹配 xxx_summary.md 格式的文件名，提取xxx部分
    match = re.match(r'^(\d+)_summary\.md$', filename)
    if match:
        return int(match.group(1))
    return None

def get_video_path(videos: List[str], file_number: int) -> Optional[str]:
    """根据文件编号获取对应的视频路径"""
    # 索引 = 文件编号 - 1
    index = file_number - 1
    
    if 0 <= index < len(videos):
        video_path = videos[index]
        if video_path:  # 确保路径不为空
            return video_path
    
    return None

def add_video_link_to_md(md_file_path: Path, video_path: str) -> bool:
    """在Markdown文件开头添加视频链接"""
    try:
        # 读取原文件内容
        with open(md_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 构建视频链接（使用Markdown格式）
        video_link = f"**原视频文件**: [{video_path}]({video_path})\n\n"
        
        # 检查是否已经添加过视频链接（避免重复添加）
        if content.startswith("**原视频文件**: `"):
            logger.warning(f"文件 {md_file_path.name} 已包含视频链接，重写中")
            # 读取文件，替换第一行，写回文件
            lines = content.split('\n', 1)
            if len(lines) > 1:
                new_content = video_link[:-1] + lines[1]
            else:
                new_content = video_link + lines[0]
        else:
            # 在文件开头添加视频链接
            new_content = video_link + content
        
        # 写回文件
        with open(md_file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        logger.info(f"已为 {md_file_path.name} 添加视频链接")
        return True
        
    except Exception as e:
        logger.error(f"处理文件 {md_file_path.name} 时出错: {e}")
        return False

def process_md_files(md_dir: str, videos_json_path: str, dry_run: bool = False) -> dict:
    """处理所有Markdown文件"""
    # 加载视频路径
    videos = load_videos_json(videos_json_path)
    
    # 获取所有Markdown文件
    md_dir_path = Path(md_dir)
    md_files = list(md_dir_path.glob("*_summary.md"))
    
    logger.info(f"找到 {len(md_files)} 个Markdown文件")
    
    # 统计信息
    stats = {
        "total_files": len(md_files),
        "processed": 0,
        "skipped_no_video": 0,
        "overwritten": 0,
        "failed": 0,
        "success": 0
    }
    
    # 处理每个文件
    for md_file in sorted(md_files):
        # 提取文件编号
        file_number = extract_file_number(md_file.name)
        
        if file_number is None:
            logger.warning(f"无法从文件名提取编号: {md_file.name}")
            stats["failed"] += 1
            continue
        
        # 获取视频路径
        video_path = get_video_path(videos, file_number)
        
        if video_path is None:
            logger.warning(f"文件 {md_file.name} (编号{file_number}) 没有对应的视频路径")
            stats["skipped_no_video"] += 1
            continue
        
        # 检查是否干运行
        if dry_run:
            logger.info(f"[干运行] 文件 {md_file.name} -> 视频: {video_path}")
            stats["processed"] += 1
            continue
        
        # 添加视频链接
        try:
            # 先检查是否已包含视频链接
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if content.startswith("**原视频文件**: `"):
                logger.info(f"文件 {md_file.name} 已包含视频链接，重写中")
                stats["overwritten"] += 1
            
            # 添加视频链接
            success = add_video_link_to_md(md_file, video_path)
            
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1
            
            stats["processed"] += 1
            
        except Exception as e:
            logger.error(f"处理文件 {md_file.name} 时出错: {e}")
            stats["failed"] += 1
    
    return stats

def main():
    parser = argparse.ArgumentParser(description='为Markdown总结文件添加原视频文件路径链接')
    parser.add_argument('--md-dir', default='D:\\QwenASR\\audio_summaries',
                       help='Markdown文件目录，默认为 D:\\QwenASR\\audio_summaries')
    parser.add_argument('--videos-json', default='D:\\QwenASR\\videos.json',
                       help='videos.json文件路径，默认为 D:\\QwenASR\\videos.json')
    parser.add_argument('--dry-run', action='store_true',
                       help='干运行模式，只显示将要进行的操作而不实际修改文件')
    
    args = parser.parse_args()
    
    logger.info("开始处理Markdown文件...")
    if args.dry_run:
        logger.info("干运行模式：只显示操作，不修改文件")
    
    try:
        stats = process_md_files(args.md_dir, args.videos_json, args.dry_run)
        
        # 输出统计信息
        logger.info("=" * 50)
        logger.info("处理完成！统计信息：")
        logger.info(f"总文件数: {stats['total_files']}")
        logger.info(f"已处理: {stats['processed']}")
        logger.info(f"成功添加链接: {stats['success']}")
        logger.info(f"跳过（无视频）: {stats['skipped_no_video']}")
        logger.info(f"跳过（已有链接）: {stats['skipped_already_has_link']}")
        logger.info(f"失败: {stats['failed']}")
        
        if not args.dry_run:
            # 显示一些示例
            logger.info("\n示例文件（前5个）：")
            md_dir_path = Path(args.md_dir)
            md_files = list(md_dir_path.glob("*_summary.md"))
            
            for i, md_file in enumerate(sorted(md_files)[:5]):
                try:
                    with open(md_file, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                    logger.info(f"  {md_file.name}: {first_line[:80]}...")
                except:
                    logger.info(f"  {md_file.name}: 无法读取")
        
    except Exception as e:
        logger.error(f"处理过程中出错: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())