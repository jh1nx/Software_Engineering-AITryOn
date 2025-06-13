// 默认设置
const DEFAULT_SETTINGS = {
  serverHost: 'localhost',
  serverPort: 8080,
  enableNotifications: true,
  enableTaskPolling: true
};

let currentSettings = { ...DEFAULT_SETTINGS };

// 扩展安装时创建右键菜单和初始化设置
chrome.runtime.onInstalled.addListener(async () => {
  chrome.contextMenus.create({
    id: "sendImageToLocal",
    title: "发送图片到本地处理软件",
    contexts: ["image"]
  });
  
  // 初始化设置
  await initializeSettings();
});

// 扩展启动时加载设置
chrome.runtime.onStartup.addListener(async () => {
  await loadSettings();
});

// 初始化设置
async function initializeSettings() {
  try {
    const result = await chrome.storage.sync.get(DEFAULT_SETTINGS);
    currentSettings = { ...result };
    console.log('设置已初始化:', currentSettings);
  } catch (error) {
    console.error('初始化设置失败:', error);
    currentSettings = { ...DEFAULT_SETTINGS };
  }
}

// 加载设置
async function loadSettings() {
  try {
    const result = await chrome.storage.sync.get(DEFAULT_SETTINGS);
    currentSettings = { ...result };
    console.log('设置已加载:', currentSettings);
  } catch (error) {
    console.error('加载设置失败:', error);
  }
}

// 获取服务器URL
function getServerUrl() {
  return `http://${currentSettings.serverHost}:${currentSettings.serverPort}`;
}

// 扩展安装时创建右键菜单
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "sendImageToLocal",
    title: "发送图片到本地处理软件",
    contexts: ["image"]
  });
});

// 处理右键菜单点击事件
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "sendImageToLocal") {
    try {
      const imageUrl = info.srcUrl;
      const pageUrl = tab.url;
      const pageTitle = tab.title;
      const favIconUrl = tab.favIconUrl;
      
      console.log("页面信息:", { pageUrl, pageTitle, favIconUrl });
      
      // 检查content script是否已注入
      try {
        await chrome.tabs.sendMessage(tab.id, { action: "ping" });
      } catch (error) {
        console.log("Content script未就绪，重新注入...");
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content-script.js']
        });
        // 等待一秒让脚本初始化
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      
      // 发送消息到content script获取图片数据
      const response = await chrome.tabs.sendMessage(tab.id, {
        action: "getImageData",
        imageUrl: imageUrl,
        pageInfo: {
          url: pageUrl,
          title: pageTitle,
          favIconUrl: favIconUrl
        }
      });
      
      console.log("Content script响应:", response);
      
      if (response && response.success) {
        await sendImageToLocalServer(response.imageData, imageUrl, response.pageInfo);
      } else {
        // 如果content script失败，使用基本页面信息
        console.log("使用基本页面信息");
        await sendImageToLocalServer(imageUrl, imageUrl, {
          url: pageUrl,
          title: pageTitle,
          favIconUrl: favIconUrl
        });
      }
    } catch (error) {
      console.error("处理图片失败:", error);
      showNotification("错误", "图片处理失败: " + error.message);
    }
  }
});

// 发送图片到本地服务器
async function sendImageToLocalServer(imageData, originalUrl, pageInfo) {
  try {
    const serverUrl = getServerUrl();
    console.log("发送到服务器:", serverUrl);
    console.log("发送数据:", { 
      imageDataType: typeof imageData,
      imageDataLength: imageData?.length || 0,
      originalUrl,
      pageInfo 
    });
    
    const response = await fetch(`${serverUrl}/api/receive-image`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        imageData: imageData,
        originalUrl: originalUrl,
        pageInfo: pageInfo,
        timestamp: Date.now(),
        source: "browser-extension"
      })
    });

    if (response.ok) {
      const result = await response.json();
      if (result.success) {
        const pageTitle = pageInfo?.title || "未知页面";
        if (currentSettings.enableNotifications) {
          showNotification("成功", `图片已发送到本地处理软件\n来源页面: ${pageTitle}\n任务ID: ${result.taskId}`);
        }
        
        // 可选：轮询检查处理状态
        if (currentSettings.enableTaskPolling) {
          pollTaskStatus(result.taskId);
        }
      } else {
        throw new Error(result.error || "服务器处理失败");
      }
    } else {
      throw new Error(`服务器响应错误: ${response.status}`);
    }
  } catch (error) {
    console.error("发送图片失败:", error);
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      const serverUrl = getServerUrl();
      showNotification("错误", `无法连接到服务器 ${serverUrl}，请检查设置和服务状态`);
    } else {
      showNotification("错误", "发送失败: " + error.message);
    }
    throw error;
  }
}

// 轮询任务状态
async function pollTaskStatus(taskId) {
  const maxAttempts = 10;
  let attempts = 0;
  const serverUrl = getServerUrl();
  
  const checkStatus = async () => {
    try {
      const response = await fetch(`${serverUrl}/api/task/${taskId}`);
      if (response.ok) {
        const result = await response.json();
        const status = result.status.status;
        
        if (status === 'completed') {
          if (currentSettings.enableNotifications) {
            showNotification("处理完成", "图片处理已完成！");
          }
          return;
        } else if (status === 'failed') {
          if (currentSettings.enableNotifications) {
            showNotification("处理失败", "图片处理失败，请查看服务器日志");
          }
          return;
        } else if (attempts < maxAttempts) {
          attempts++;
          setTimeout(checkStatus, 2000);
        }
      }
    } catch (error) {
      console.error("检查任务状态失败:", error);
    }
  };
  
  setTimeout(checkStatus, 1000);
}

// 显示通知
function showNotification(title, message) {
  try {
    if (chrome.notifications && currentSettings.enableNotifications) {
      chrome.notifications.create({
        type: "basic",
        title: title,
        message: message
      }, (notificationId) => {
        if (chrome.runtime.lastError) {
          console.error("通知创建失败:", chrome.runtime.lastError.message);
          console.log(`通知: ${title} - ${message}`);
        } else {
          console.log("通知已显示:", notificationId);
        }
      });
    } else {
      console.log(`通知: ${title} - ${message}`);
    }
  } catch (error) {
    console.error("显示通知失败:", error);
    console.log(`通知: ${title} - ${message}`);
  }
}

// 监听来自popup和options的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "checkServerStatus") {
    checkServerConnection().then(sendResponse);
    return true;
  } else if (request.action === "settingsUpdated") {
    currentSettings = { ...request.settings };
    console.log("设置已更新:", currentSettings);
    sendResponse({ success: true });
  } else if (request.action === "getSettings") {
    sendResponse(currentSettings);
  }
});

// 检查本地服务器连接状态
async function checkServerConnection() {
  try {
    const serverUrl = getServerUrl();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    
    const response = await fetch(`${serverUrl}/api/status`, {
      method: "GET",
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    return { 
      connected: response.ok, 
      serverUrl: serverUrl,
      settings: currentSettings
    };
  } catch (error) {
    return { 
      connected: false, 
      error: error.message,
      serverUrl: getServerUrl(),
      settings: currentSettings
    };
  }
}

// 监听存储变化
chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'sync') {
    console.log('存储发生变化:', changes);
    loadSettings();
  }
});