document.addEventListener('DOMContentLoaded', function() {
  const serverStatus = document.getElementById('serverStatus');
  const statusText = document.getElementById('statusText');
  const refreshButton = document.getElementById('refreshStatus');
  
  // 添加状态缓存
  let lastStatusCheck = 0;
  let cachedStatus = null;
  
  // 添加设置链接
  addSettingsLink();
  
  // 初始检查服务器状态
  checkServerStatus();
  
  // 刷新按钮点击事件
  refreshButton.addEventListener('click', () => {
    checkServerStatus(true);
  });
  
  // 添加设置链接
  function addSettingsLink() {
    const settingsContainer = document.createElement('div');
    settingsContainer.style.cssText = 'text-align: center; margin-top: 15px; padding-top: 15px; border-top: 1px solid #ddd;';
    
    const settingsLink = document.createElement('button');
    settingsLink.textContent = '打开设置';
    settingsLink.style.cssText = `
      background: #f0f0f0;
      border: 1px solid #ccc;
      padding: 5px 10px;
      border-radius: 3px;
      cursor: pointer;
      font-size: 12px;
    `;
    
    settingsLink.addEventListener('click', () => {
      chrome.runtime.openOptionsPage();
    });
    
    settingsContainer.appendChild(settingsLink);
    document.body.appendChild(settingsContainer);
  }
  
  // 检查服务器状态
  function checkServerStatus(forceRefresh = false) {
    const now = Date.now();
    
    if (!forceRefresh && cachedStatus && (now - lastStatusCheck < 5000)) {
      updateStatusDisplay(cachedStatus);
      return;
    }
    
    statusText.textContent = '检查中...';
    refreshButton.disabled = true;
    
    chrome.runtime.sendMessage(
      { action: 'checkServerStatus' },
      (response) => {
        if (chrome.runtime.lastError) {
          console.error('通信错误:', chrome.runtime.lastError.message);
          updateStatusDisplay({ 
            connected: false, 
            error: '扩展通信失败' 
          });
        } else {
          cachedStatus = response;
          lastStatusCheck = now;
          updateStatusDisplay(response);
        }
        refreshButton.disabled = false;
      }
    );
  }
  
  // 更新状态显示
  function updateStatusDisplay(response) {
    if (response && response.connected) {
      serverStatus.className = 'status connected';
      statusText.textContent = `已连接 (${response.serverUrl})`;
      showTemporaryMessage('连接正常', 'success');
    } else {
      serverStatus.className = 'status disconnected';
      let errorMsg = '本地服务器未启动';
      
      if (response?.serverUrl) {
        errorMsg = `无法连接到 ${response.serverUrl}`;
      }
      
      if (response?.error) {
        errorMsg += ` (${response.error})`;
      }
      
      statusText.textContent = errorMsg;
      showTemporaryMessage('请检查服务器和设置', 'error');
    }
    
    // 显示当前设置信息
    if (response?.settings) {
      updateSettingsInfo(response.settings);
    }
  }
  
  // 更新设置信息显示
  function updateSettingsInfo(settings) {
    // 移除旧的设置信息
    const oldInfo = document.querySelector('.settings-info');
    if (oldInfo) {
      oldInfo.remove();
    }
    
    // 创建设置信息显示
    const settingsInfo = document.createElement('div');
    settingsInfo.className = 'settings-info';
    settingsInfo.style.cssText = `
      font-size: 11px;
      color: #666;
      margin-top: 10px;
      padding: 8px;
      background: #f9f9f9;
      border-radius: 3px;
      border: 1px solid #e0e0e0;
    `;
    
    settingsInfo.innerHTML = `
      <div style="margin-bottom: 3px;"><strong>当前设置:</strong></div>
      <div>服务器: ${settings.serverHost}:${settings.serverPort}</div>
      <div>通知: ${settings.enableNotifications ? '启用' : '禁用'}</div>
      <div>状态检查: ${settings.enableTaskPolling ? '启用' : '禁用'}</div>
    `;
    
    // 插入到刷新按钮后面
    refreshButton.parentNode.insertBefore(settingsInfo, refreshButton.nextSibling);
  }
  
  // 显示临时消息
  function showTemporaryMessage(message, type) {
    const messageEl = document.createElement('div');
    messageEl.className = `temp-message ${type}`;
    messageEl.textContent = message;
    messageEl.style.cssText = `
      position: absolute;
      top: 10px;
      right: 10px;
      padding: 5px 10px;
      border-radius: 3px;
      font-size: 12px;
      z-index: 1000;
      opacity: 0;
      transition: opacity 0.3s;
      ${type === 'success' ? 'background: #4CAF50; color: white;' : 'background: #f44336; color: white;'}
    `;
    
    document.body.appendChild(messageEl);
    
    setTimeout(() => messageEl.style.opacity = '1', 10);
    
    setTimeout(() => {
      messageEl.style.opacity = '0';
      setTimeout(() => {
        if (messageEl.parentNode) {
          messageEl.parentNode.removeChild(messageEl);
        }
      }, 300);
    }, 3000);
  }
  
  // 定期检查服务器状态
  setInterval(checkServerStatus, 30000);
  
  // 页面可见性变化时检查状态
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      checkServerStatus();
    }
  });
  
  // 添加键盘快捷键支持
  document.addEventListener('keydown', (e) => {
    if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
      e.preventDefault();
      checkServerStatus(true);
    }
  });
});