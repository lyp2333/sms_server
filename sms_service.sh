#!/bin/bash

# 确保脚本以root权限运行
if [ "$(id -u)" -ne 0 ]; then
    echo "请使用sudo运行此脚本"
    exit 1
fi

# 创建systemd服务文件
cat > /etc/systemd/system/sms-webhook.service << 'EOF'
[Unit]
Description=SMS Webhook Service
After=network.target

[Service]
User=root
WorkingDirectory=/home/lyp/code/sms_server
EnvironmentFile=/home/lyp/code/sms_server/.env
ExecStart=/home/lyp/.conda/envs/sms/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8322
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 重新加载systemd配置
systemctl daemon-reload

# 启用并启动服务
systemctl enable sms-webhook.service
systemctl start sms-webhook.service

echo "SMS Webhook服务已安装并启动"
echo "查看状态: systemctl status sms-webhook.service"
echo "查看日志: journalctl -u sms-webhook.service"