// 默认设置
const DEFAULT_SETTINGS = {
  serverHost: 'localhost',
  serverPort: 8080,
  enableNotifications: true,
  enableTaskPolling: true
};

document.addEventListener('DOMContentLoaded', function() {
  // 获取页面元素
  const serverHostInput = document.getElementById('serverHost');
  const serverPortInput = document.getElementById('serverPort');
  const enableNotificationsCheckbox = document.getElementById('enableNotifications');
  const enableTaskPollingCheckbox = document.getElementById('enableTaskPolling');
  const saveButton = document.getElementById('saveSettings');
  const resetButton = document.getElementById('resetSettings');
  const testButton = document.getElementById('testConnection');
  const statusMessage = document.getElementById('statusMessage');
  const connectionStatus = document.getElementById('connectionStatus');
  
  // 加载已保存的设置
  loadSettings();
  
  // 绑定事件监听器
  saveButton.addEventListener('click', saveSettings);
  resetButton.addEventListener('click', resetSettings);
  testButton.addEventListener('click', testConnection);
  
  // 端口号输入验证
  serverPortInput.addEventListener('input', validatePort);
  
  // 加载设置
  async function loadSettings() {
    try {
      const result = await chrome.storage.sync.get(DEFAULT_SETTINGS);
      
      serverHostInput.value = result.serverHost;
      serverPortInput.value = result.serverPort;
      enableNotificationsCheckbox.checked = result.enableNotifications;
      enableTaskPollingCheckbox.checked = result.enableTaskPolling;
      
      console.log('设置已加载:', result);
    } catch (error) {
      console.error('加载设置失败:', error);
      showMessage('加载设置失败', 'error');
    }
  }
  
  // 保存设置
  async function saveSettings() {
    try {
      // 验证输入
      if (!validateInputs()) {
        return;
      }
      
      const settings = {
        serverHost: serverHostInput.value.trim() || 'localhost',
        serverPort: parseInt(serverPortInput.value) || 8080,
        enableNotifications: enableNotificationsCheckbox.checked,
        enableTaskPolling: enableTaskPollingCheckbox.checked
      };
      
      // 保存到存储
      await chrome.storage.sync.set(settings);
      
      // 通知background script设置已更新
      chrome.runtime.sendMessage({ 
        action: 'settingsUpdated', 
        settings: settings 
      });
      
      showMessage('设置已保存', 'success');
      console.log('设置已保存:', settings);
    } catch (error) {
      console.error('保存设置失败:', error);
      showMessage('保存设置失败: ' + error.message, 'error');
    }
  }
  
  // 重置设置
  async function resetSettings() {
    try {
      await chrome.storage.sync.set(DEFAULT_SETTINGS);
      await loadSettings();
      
      // 通知background script设置已更新
      chrome.runtime.sendMessage({ 
        action: 'settingsUpdated', 
        settings: DEFAULT_SETTINGS 
      });
      
      showMessage('设置已重置为默认值', 'success');
      console.log('设置已重置');
    } catch (error) {
      console.error('重置设置失败:', error);
      showMessage('重置设置失败: ' + error.message, 'error');
    }
  }
  
  // 测试连接
  async function testConnection() {
    const host = serverHostInput.value.trim() || 'localhost';
    const port = parseInt(serverPortInput.value) || 8080;
    
    if (!validatePort()) {
      return;
    }
    
    testButton.disabled = true;
    testButton.textContent = '测试中...';
    connectionStatus.style.display = 'none';
    
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      
      const response = await fetch(`http://${host}:${port}/api/status`, {
        method: 'GET',
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (response.ok) {
        const result = await response.json();
        showConnectionStatus('连接成功', 'connected');
        console.log('服务器响应:', result);
      } else {
        showConnectionStatus(`连接失败 (HTTP ${response.status})`, 'disconnected');
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        showConnectionStatus('连接超时', 'disconnected');
      } else {
        showConnectionStatus('连接失败: ' + error.message, 'disconnected');
      }
    } finally {
      testButton.disabled = false;
      testButton.textContent = '测试连接';
    }
  }
  
  // 验证输入
  function validateInputs() {
    return validatePort();
  }
  
  // 验证端口号
  function validatePort() {
    const port = parseInt(serverPortInput.value);
    
    if (isNaN(port) || port < 1000 || port > 65535) {
      showMessage('端口号必须在1000-65535范围内', 'error');
      serverPortInput.focus();
      return false;
    }
    
    return true;
  }
  
  // 显示状态消息
  function showMessage(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = `status-message ${type}`;
    statusMessage.style.display = 'block';
    
    // 3秒后自动隐藏
    setTimeout(() => {
      statusMessage.style.display = 'none';
    }, 3000);
  }
  
  // 显示连接状态
  function showConnectionStatus(message, type) {
    connectionStatus.textContent = message;
    connectionStatus.className = `connection-status ${type}`;
    connectionStatus.style.display = 'block';
  }
});
