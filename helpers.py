import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import time
import psutil
import os
from logging.handlers import TimedRotatingFileHandler
import telegram

def format_trade_message(side, symbol, price, amount, total, grid_size, retry_count=None):
    """格式化交易消息为美观的文本格式
    
    Args:
        side (str): 交易方向 ('buy' 或 'sell')
        symbol (str): 交易对
        price (float): 交易价格
        amount (float): 交易数量
        total (float): 交易总额
        grid_size (float): 网格大小
        retry_count (tuple, optional): 重试次数，格式为 (当前次数, 最大次数)
    
    Returns:
        str: 格式化后的消息文本
    """
    # 使用emoji增加可读性
    direction_emoji = "🟢" if side == 'buy' else "🔴"
    direction_text = "买入" if side == 'buy' else "卖出"
    
    # 构建消息主体
    message = f"""
{direction_emoji} {direction_text} {symbol}
━━━━━━━━━━━━━━━━━━━━
💰 价格：{price:.2f} USDT
📊 数量：{amount:.4f} BNB
💵 金额：{total:.2f} USDT
📈 网格：{grid_size}%
"""
    
    # 如果有重试信息，添加重试次数
    if retry_count:
        current, max_retries = retry_count
        message += f"🔄 尝试：{current}/{max_retries}次\n"
    
    # 添加时间戳
    message += f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    
    return message

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def safe_fetch(method, *args, **kwargs):
    try:
        return await method(*args, **kwargs)
    except Exception as e:
        logging.error(f"请求失败: {str(e)}")
        raise 

def debug_watcher():
    """资源监控装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.time()
            mem_before = psutil.virtual_memory().used
            logging.debug(f"[DEBUG] 开始执行 {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                cost = time.time() - start
                mem_used = psutil.virtual_memory().used - mem_before
                logging.debug(f"[DEBUG] {func.__name__} 执行完成 | 耗时: {cost:.3f}s | 内存变化: {mem_used/1024/1024:.2f}MB")
        return wrapper
    return decorator 

class LogConfig:
    SINGLE_LOG = True  # 强制单文件模式
    BACKUP_DAYS = 2    # 保留2天日志
    LOG_DIR = os.path.dirname(__file__)  # 与main.py相同目录
    LOG_LEVEL = logging.INFO

    @staticmethod
    def setup_logger():
        logger = logging.getLogger()
        logger.setLevel(LogConfig.LOG_LEVEL)
        
        # 清理所有现有处理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 文件处理器
        file_handler = TimedRotatingFileHandler(
            os.path.join(LogConfig.LOG_DIR, 'trading_system.log'),
            when='midnight',
            interval=1,
            backupCount=LogConfig.BACKUP_DAYS,
            encoding='utf-8',
            delay=True
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    @staticmethod
    def clean_old_logs():
        if not os.path.exists(LogConfig.LOG_DIR):
            return
        now = time.time()
        for fname in os.listdir(LogConfig.LOG_DIR):
            if LogConfig.SINGLE_LOG and fname != 'trading_system.log':
                continue
            path = os.path.join(LogConfig.LOG_DIR, fname)
            if os.stat(path).st_mtime < now - LogConfig.BACKUP_DAYS * 86400:
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"删除旧日志失败 {fname}: {str(e)}") 

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def send_telegram_message(content, title="交易通知"):
    """Sends a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("未配置TELEGRAM_BOT_TOKEN或TELEGRAM_CHAT_ID，无法发送Telegram通知")
        return

    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    full_message = f"*{title}*\n\n{content}" # Use Markdown for title

    try:
        logging.info(f"正在发送Telegram通知: {title}")
        # Split message if too long (Telegram limit is 4096 chars)
        max_length = 4000 # Leave some margin
        if len(full_message) > max_length:
             logging.warning(f"消息过长 ({len(full_message)} chars)，将被截断.")
             # Basic truncation, could be improved to split nicely
             full_message = full_message[:max_length] + "..."

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=full_message,
            parse_mode=telegram.constants.ParseMode.MARKDOWN # Use Markdown
        )
        logging.info(f"Telegram消息发送成功")
    except telegram.error.TelegramError as e:
        logging.error(f"Telegram消息发送失败: {e}")
        # Reraise to allow tenacity retry
        raise
    except Exception as e:
        logging.error(f"发送Telegram消息时发生未知错误: {str(e)}", exc_info=True)
        # Reraise unexpected errors as well
        raise 
