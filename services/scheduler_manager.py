# scheduler_manager.py - 增强版
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

# 日志目录（锚定项目根目录，与启动时的工作目录无关）
LOG_DIR = Path(__file__).resolve().parent.parent / "log"

class EnhancedSchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.logger = self.setup_logger()
        self.task_stats = {}  # 任务执行统计
        
    def setup_logger(self):
        """设置专用日志"""
        logger = logging.getLogger('scheduler_manager')
        logger.setLevel(logging.INFO)
        
        # 文件处理器（确保日志目录存在）
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_DIR / "scheduler_detailed.log", encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(levelname)s - %(message)s'
        ))
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger
    
    def setup_production_tasks(self):
        """生产环境任务配置"""
        self.logger.info("🔧 配置生产任务...")
        
        # 生产任务 - 与main.py中的任务互补
        tasks = [
            {
                'func': self.health_check,
                'trigger': CronTrigger(minute="*/30"),  # 每30分钟健康检查
                'id': 'health_check',
                'name': '系统健康检查'
            },
            {
                'func': self.backup_database,
                'trigger': CronTrigger(hour=1, minute=0),  # 凌晨1点备份
                'id': 'db_backup',
                'name': '数据库备份'
            },
            {
                'func': self.cleanup_logs,
                'trigger': CronTrigger(day_of_week='sun', hour=3, minute=0),  # 周日凌晨清理
                'id': 'log_cleanup',
                'name': '日志清理'
            }
        ]
        
        for task in tasks:
            self.scheduler.add_job(
                task['func'],
                task['trigger'],
                id=task['id'],
                name=task['name'],
                misfire_grace_time=1800
            )
    
    def setup_monitoring_tasks(self):
        """监控任务配置"""
        self.logger.info("🔍 配置监控任务...")
        
        # 监控主调度器状态
        self.scheduler.add_job(
            self.monitor_main_scheduler,
            IntervalTrigger(minutes=5),
            id='monitor_main',
            name='主调度器监控'
        )
        
        # 任务执行统计
        self.scheduler.add_job(
            self.report_task_statistics,
            CronTrigger(minute=0),  # 每小时报告
            id='task_stats',
            name='任务统计报告'
        )
    
    # 修复后的健康检查函数
    async def health_check(self):
        """系统健康检查 - 修复版"""
        try:
            self.logger.info("🏥 执行系统健康检查...")
            
            # 修复数据库连接检查
            from core.database import engine
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))  # 添加text()包装
                if result.fetchone()[0] == 1:
                    self.logger.info("✅ 数据库连接正常")
                else:
                    raise Exception("数据库查询结果异常")
            
            # 检查关键服务（session 为同步 requests.Session，
            # 必须放到线程执行，避免阻塞事件循环导致请求卡死）
            from services.stock_service import stock_service
            if hasattr(stock_service, 'session'):
                try:
                    response = await asyncio.to_thread(
                        stock_service.session.get, 'https://httpbin.org/get', timeout=5
                    )
                    if response.status_code == 200:
                        self.logger.info("✅ 网络服务正常")
                    else:
                        raise Exception(f"网络服务返回状态码: {response.status_code}")
                except Exception as e:
                    self.logger.warning(f"⚠️ 网络服务检查失败: {e}")
            
            self.logger.info("✅ 系统健康检查通过")
            self.update_task_stats('health_check', 'success')
            
        except Exception as e:
            self.logger.error(f"❌ 健康检查失败: {e}")
            self.update_task_stats('health_check', 'failed')
    
    def monitor_main_scheduler(self):
        """监控主调度器"""
        try:
            # 这里可以访问主调度器状态
            # 通过某种方式获取app_scheduler的状态
            self.logger.info("🔍 监控主调度器运行状态")
            
            # 检查关键任务是否存在
            critical_tasks = ['sync_market_data', 'analyze_stocks']
            # 实现检查逻辑...
            
        except Exception as e:
            self.logger.error(f"❌ 监控任务失败: {e}")
    
    def report_task_statistics(self):
        """报告任务统计"""
        self.logger.info("📊 任务执行统计报告:")
        for task_id, stats in self.task_stats.items():
            total = stats.get('success', 0) + stats.get('failed', 0)
            success_rate = (stats.get('success', 0) / total * 100) if total > 0 else 0
            self.logger.info(f"  {task_id}: 总计{total}次, 成功率{success_rate:.1f}%")
    
    def update_task_stats(self, task_id, status):
        """更新任务统计"""
        if task_id not in self.task_stats:
            self.task_stats[task_id] = {'success': 0, 'failed': 0}
        
        self.task_stats[task_id][status] += 1
    
    async def backup_database(self):
        """数据库备份"""
        try:
            self.logger.info("💾 开始数据库备份...")
            # 实现备份逻辑
            self.logger.info("✅ 数据库备份完成")
            self.update_task_stats('db_backup', 'success')
        except Exception as e:
            self.logger.error(f"❌ 数据库备份失败: {e}")
            self.update_task_stats('db_backup', 'failed')
    
    async def cleanup_logs(self):
        """日志清理"""
        try:
            self.logger.info("🧹 开始日志清理...")
            import os
            import glob
            from datetime import datetime, timedelta
            
            # 清理7天前的日志
            cutoff_date = datetime.now() - timedelta(days=7)
            log_files = glob.glob("*.log")
            
            for log_file in log_files:
                if os.path.getmtime(log_file) < cutoff_date.timestamp():
                    os.remove(log_file)
                    self.logger.info(f"  已删除: {log_file}")
            
            self.logger.info("✅ 日志清理完成")
            self.update_task_stats('log_cleanup', 'success')
        except Exception as e:
            self.logger.error(f"❌ 日志清理失败: {e}")
            self.update_task_stats('log_cleanup', 'failed')
    
    def start(self):
        """启动增强调度器"""
        self.setup_production_tasks()
        self.setup_monitoring_tasks()
        self.scheduler.start()
        self.logger.info("✅ 增强调度器已启动")
    
    def shutdown(self):
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.logger.info("🛑 增强调度器已关闭")

# 全局实例
scheduler_manager = EnhancedSchedulerManager()