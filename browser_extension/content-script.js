// 监听来自background script的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log("Content script收到消息:", request);
  
  if (request.action === "ping") {
    sendResponse({ success: true, message: "pong" });
    return;
  }
  
  if (request.action === "getImageData") {
    handleImageDataRequest(request)
      .then(result => {
        console.log("处理结果:", result);
        sendResponse(result);
      })
      .catch(error => {
        console.error("获取图片数据失败:", error);
        sendResponse({ success: false, error: error.message });
      });
    return true; // 保持消息通道开放
  }
});

// 处理图片数据请求
async function handleImageDataRequest(request) {
  try {
    const { imageUrl, pageInfo } = request;
    
    console.log("开始处理图片数据:", imageUrl);
    console.log("页面信息:", pageInfo);
    
    // 获取图片数据
    const imageData = await getImageAsBase64(imageUrl);
    
    // 获取页面上下文信息
    const contextInfo = getImageContext(imageUrl);
    
    const result = {
      success: true,
      imageData: imageData,
      pageInfo: {
        ...pageInfo,
        ...contextInfo,
        documentTitle: document.title,
        documentUrl: window.location.href,
        timestamp: Date.now()
      }
    };
    
    console.log("最终页面信息:", result.pageInfo);
    return result;
  } catch (error) {
    console.error("处理图片数据失败:", error);
    throw new Error(`处理图片数据失败: ${error.message}`);
  }
}

// 将图片转换为Base64格式
async function getImageAsBase64(imageUrl) {
  try {
    // 创建一个新的Image对象
    const img = new Image();
    img.crossOrigin = "anonymous";
    
    return new Promise((resolve, reject) => {
      img.onload = function() {
        try {
          // 创建canvas来转换图片
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');
          
          canvas.width = img.naturalWidth || img.width;
          canvas.height = img.naturalHeight || img.height;
          
          // 绘制图片到canvas
          ctx.drawImage(img, 0, 0);
          
          // 转换为Base64
          const dataURL = canvas.toDataURL('image/png', 0.8);
          resolve(dataURL);
        } catch (error) {
          reject(error);
        }
      };
      
      img.onerror = function() {
        // 如果直接转换失败，尝试通过fetch获取
        fetchImageAsBase64(imageUrl)
          .then(resolve)
          .catch(reject);
      };
      
      img.src = imageUrl;
    });
  } catch (error) {
    throw new Error(`图片转换失败: ${error.message}`);
  }
}

// 通过fetch获取图片并转换为Base64
async function fetchImageAsBase64(imageUrl) {
  try {
    const response = await fetch(imageUrl);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    const blob = await response.blob();
    
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch (error) {
    // 如果fetch也失败，返回原始URL
    return imageUrl;
  }
}

// 获取图片在页面中的上下文信息
function getImageContext(imageUrl) {
  try {
    // 查找页面中对应的图片元素
    const imgElements = document.querySelectorAll('img');
    let targetImg = null;
    
    for (const img of imgElements) {
      if (img.src === imageUrl || img.currentSrc === imageUrl) {
        targetImg = img;
        break;
      }
    }
    
    if (!targetImg) {
      return {
        contextFound: false,
        imageContext: null
      };
    }
    
    // 获取图片周围的文本内容
    const parentElement = targetImg.parentElement;
    let contextText = '';
    
    // 尝试获取图片的alt属性或title属性
    const altText = targetImg.alt || targetImg.title || '';
    
    // 获取父元素的文本内容（限制长度）
    if (parentElement) {
      const parentText = parentElement.textContent || '';
      contextText = parentText.substring(0, 200).trim();
    }
    
    // 获取图片的位置信息
    const rect = targetImg.getBoundingClientRect();
    
    return {
      contextFound: true,
      imageContext: {
        altText: altText,
        contextText: contextText,
        position: {
          top: rect.top,
          left: rect.left,
          width: rect.width,
          height: rect.height
        },
        parentTagName: parentElement ? parentElement.tagName : null,
        imageDimensions: {
          naturalWidth: targetImg.naturalWidth,
          naturalHeight: targetImg.naturalHeight,
          displayWidth: targetImg.width,
          displayHeight: targetImg.height
        }
      }
    };
  } catch (error) {
    console.error("获取图片上下文失败:", error);
    return {
      contextFound: false,
      error: error.message
    };
  }
}

// 为图片添加悬停效果（可选）
function addImageHoverEffect() {
  const style = document.createElement('style');
  style.textContent = `
    .extension-image-hover {
      outline: 2px solid #4CAF50 !important;
      outline-offset: 2px !important;
      transition: outline 0.2s ease !important;
    }
  `;
  document.head.appendChild(style);
  
  // 为所有图片添加悬停效果
  document.querySelectorAll('img').forEach(img => {
    img.addEventListener('mouseenter', function() {
      this.classList.add('extension-image-hover');
    });
    
    img.addEventListener('mouseleave', function() {
      this.classList.remove('extension-image-hover');
    });
  });
}

// 页面加载完成后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    addImageHoverEffect();
  });
} else {
  addImageHoverEffect();
}

// 添加初始化日志
console.log("Content script已加载");