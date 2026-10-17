"""Internal status identifiers and Chinese display labels."""
FAILED = {"QUERY-FAILED", "CONNECTION-FAILED", "UPDATE-FAILED", "CANCELLED"}
ACTIVE = {"QUEUED", "CHECKING", "UPDATING", "VERIFYING"}
LABELS = {
    "QUEUED": "等待检查", "CHECKING": "检查版本", "CURRENT": "已是最新",
    "AVAILABLE": "发现新版本", "UPDATING": "正在更新", "VERIFYING": "核验版本",
    "UPDATED": "更新成功", "QUERY-FAILED": "查询失败", "CONNECTION-FAILED": "连接失败",
    "UPDATE-FAILED": "更新失败", "CANCELLED": "已停止", "SKIPPED": "未安装，跳过",
    "INSTALLED": "已安装", "MANUAL": "需要手动更新",
}
