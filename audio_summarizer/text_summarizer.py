#!/usr/bin/env python3
"""
音频逐字稿总结程序
将对话逐字稿发送给DeepSeek API进行总结
"""

import os
import sys
import json
import argparse
import logging
import time
import concurrent.futures
from pathlib import Path
from typing import List, Set, Dict, Tuple
from openai import OpenAI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "input_dir": "D:\\QwenASR\\audio_text",
    "output_dir": "D:\\QwenASR\\audio_summaries",
    "skip_file": "D:\\QwenASR\\skips.json",
    "config_file": "D:\\QwenASR\\config.json"
}

# DeepSeek API请求的提示词
SYSTEM_PROMPT = """请总结以下逐字稿的主要内容，每一行是一句话，冒号前是说话人ID，冒号后是说话内容。
要求：使用Markdown格式输出总结，把说话人的意思表达清楚，重要的语段详细一些，6000字以内即可。如果能推断出说话人身份，可以省略说话人ID，直接用身份称呼，并在结尾注明身份对应的说话人ID。
注意：以下文字是AI从音频中识别的，可能会有一些不必要的语气词，请适当忽略。说话人普通话不标准、说话不流利等因素都可能导致识别不准，遇到错误时请适当根据上下文推测。"""


def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"配置文件格式错误: {config_path}")
        sys.exit(1)


def load_skip_file(skip_file_path: str) -> Set[int]:
    """加载跳过文件列表"""
    try:
        with open(skip_file_path, 'r', encoding='utf-8') as f:
            skip_list = json.load(f)
        return set(skip_list)
    except FileNotFoundError:
        logger.warning(f"跳过文件不存在: {skip_file_path}")
        return set()
    except json.JSONDecodeError:
        logger.warning(f"跳过文件格式错误: {skip_file_path}")
        return set()


def get_file_list(input_dir: str, from_num: int, to_num: int, 
                  skip_numbers: Set[int], use_skip_file: bool,
                  skip_file_path: str) -> List[Tuple[int, Path]]:
    """获取需要处理的文件列表"""
    files = []
    
    # 如果需要使用跳过文件，加载跳过列表
    if use_skip_file:
        skip_from_file = load_skip_file(skip_file_path)
        skip_numbers = skip_numbers.union(skip_from_file)
    
    # 遍历指定范围内的文件
    for num in range(from_num, to_num + 1):
        # 跳过指定的编号
        if num in skip_numbers:
            logger.info(f"跳过文件: {num:03d}.txt")
            continue
            
        file_path = Path(input_dir) / f"{num:03d}.txt"
        if file_path.exists():
            files.append((num, file_path))
        else:
            logger.warning(f"文件不存在: {file_path}")
    
    logger.info(f"找到 {len(files)} 个需要处理的文件")
    return files


def summarize_text(client: OpenAI, text: str) -> str:
    """调用DeepSeek API进行总结"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            stream=False,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"API调用失败: {e}")
        raise


def process_file(file_info: Tuple[int, Path], output_dir: Path, 
                 api_key: str, retry_count: int = 3) -> bool:
    """处理单个文件"""
    num, file_path = file_info
    output_path = output_dir / f"{num:03d}_summary.md"
    
    # 如果输出文件已存在，跳过
    if output_path.exists():
        logger.info(f"文件 {num:03d} 已处理，跳过")
        return True
    
    logger.info(f"开始处理文件: {file_path.name}")
    
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 创建OpenAI客户端
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        
        # 重试机制
        for attempt in range(retry_count):
            try:
                # 调用API进行总结
                summary = summarize_text(client, content)
                
                # 保存结果
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(summary)
                
                logger.info(f"文件 {num:03d} 处理完成，保存到: {output_path}")
                return True
                
            except Exception as e:
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"第 {attempt + 1} 次尝试失败，{wait_time}秒后重试: {e}")
                    time.sleep(wait_time)
                else:
                    raise
        
    except Exception as e:
        logger.error(f"处理文件 {file_path.name} 失败: {e}")
        return False
    
    return True


def distribute_files(files: List[Tuple[int, Path]], num_processes: int) -> List[List[Tuple[int, Path]]]:
    """将文件尽可能平均地分配给多个进程"""
    if num_processes <= 0:
        num_processes = 1
    
    # 创建进程列表
    processes_files = [[] for _ in range(num_processes)]
    
    # 平均分配文件
    for i, file_info in enumerate(files):
        process_idx = i % num_processes
        processes_files[process_idx].append(file_info)
    
    # 打印分配情况
    for i, file_list in enumerate(processes_files):
        if file_list:
            file_nums = [str(num) for num, _ in file_list]
            logger.info(f"进程 {i+1}: 分配 {len(file_list)} 个文件 [{', '.join(file_nums[:5])}{'...' if len(file_nums) > 5 else ''}]")
    
    return processes_files


def process_files_parallel(file_list: List[Tuple[int, Path]], output_dir: Path, 
                          api_key: str, process_id: int = 0) -> Tuple[int, int]:
    """并行处理文件列表"""
    success_count = 0
    fail_count = 0
    
    for file_info in file_list:
        success = process_file(file_info, output_dir, api_key)
        if success:
            success_count += 1
        else:
            fail_count += 1
    
    return success_count, fail_count


def main():
    parser = argparse.ArgumentParser(description='音频逐字稿总结程序')
    parser.add_argument('--input-dir', default=DEFAULT_CONFIG["input_dir"],
                       help='输入文件夹路径，默认为 D:\\QwenASR\\audio_text')
    parser.add_argument('--output-dir', default=DEFAULT_CONFIG["output_dir"],
                       help='输出文件夹路径，默认为 D:\\QwenASR\\audio_summaries')
    parser.add_argument('--processes', type=int, default=1,
                       help='同时请求进程数，默认为1')
    parser.add_argument('--from-number', type=int, required=True,
                       help='从第几号文件开始处理（包含本数）')
    parser.add_argument('--to-number', type=int, required=True,
                       help='到第几号文件结束处理（包含本数）')
    parser.add_argument('--skip', type=int, nargs='+', default=[],
                       help='跳过处理的文件编号（空格分隔）')
    parser.add_argument('--skip-file', default=DEFAULT_CONFIG["skip_file"],
                       help='跳过文件路径，默认为 D:\\QwenASR\\skips.json')
    parser.add_argument('--use-skip-file', action='store_true',
                       help='使用skip_file取代--skip参数')
    parser.add_argument('--config-file', default=DEFAULT_CONFIG["config_file"],
                       help='配置文件路径，默认为 D:\\QwenASR\\config.json')
    
    args = parser.parse_args()
    
    # 验证参数
    if args.from_number > args.to_number:
        logger.error("--from-number 不能大于 --to-number")
        sys.exit(1)
    
    if args.processes < 1:
        logger.error("--processes 必须大于0")
        sys.exit(1)
    
    # 加载配置
    config = load_config(args.config_file)
    api_key = config.get("deepseek-api-key")
    
    if not api_key:
        logger.error("配置文件中未找到 deepseek-api-key")
        sys.exit(1)
    
    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取文件列表
    skip_numbers = set(args.skip)
    files = get_file_list(args.input_dir, args.from_number, args.to_number,
                         skip_numbers, args.use_skip_file, args.skip_file)
    
    if not files:
        logger.warning("没有找到需要处理的文件")
        return
    
    # 分配文件给各个进程
    processes_files = distribute_files(files, args.processes)
    
    # 并行处理
    total_success = 0
    total_fail = 0
    
    if args.processes == 1:
        # 单进程处理
        logger.info("使用单进程模式")
        success, fail = process_files_parallel(files, output_dir, api_key)
        total_success += success
        total_fail += fail
    else:
        # 多进程处理
        logger.info(f"使用 {args.processes} 个进程并行处理")
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.processes) as executor:
            futures = []
            for i, file_list in enumerate(processes_files):
                if file_list:  # 只提交有文件的进程
                    future = executor.submit(process_files_parallel, file_list, 
                                           output_dir, api_key, i)
                    futures.append(future)
            
            # 收集结果
            for future in concurrent.futures.as_completed(futures):
                try:
                    success, fail = future.result()
                    total_success += success
                    total_fail += fail
                except Exception as e:
                    logger.error(f"进程执行失败: {e}")
                    total_fail += 1
    
    # 输出统计信息
    logger.info("=" * 50)
    logger.info(f"处理完成!")
    logger.info(f"成功: {total_success} 个文件")
    logger.info(f"失败: {total_fail} 个文件")
    logger.info(f"总计: {len(files)} 个文件")
    
    if total_fail > 0:
        logger.warning(f"有 {total_fail} 个文件处理失败，请检查日志")


if __name__ == "__main__":
    main()