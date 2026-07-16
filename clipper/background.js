chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "clip-to-second-brain",
    title: "Clip to Second Brain",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "clip-to-second-brain") {
    if (info.selectionText && tab) {
      const url = tab.url;
      const title = tab.title || "Web Clip";
      
      fetch('http://localhost:8000/api/clip', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          title: title,
          url: url,
          content: info.selectionText
        })
      })
      .then(response => {
        if (response.ok) {
          console.log("Successfully clipped to Second Brain!");
          chrome.scripting.executeScript({
            target: {tabId: tab.id},
            func: () => {
               const el = document.createElement('div');
               el.style.position = 'fixed';
               el.style.top = '20px';
               el.style.right = '20px';
               el.style.padding = '12px 24px';
               el.style.background = '#10b981';
               el.style.color = '#fff';
               el.style.borderRadius = '8px';
               el.style.zIndex = '999999';
               el.style.fontFamily = 'sans-serif';
               el.style.boxShadow = '0 10px 25px rgba(0,0,0,0.2)';
               el.innerText = 'Clipped to Second Brain! 🧠';
               document.body.appendChild(el);
               setTimeout(() => {
                  el.style.transition = 'opacity 0.5s';
                  el.style.opacity = '0';
                  setTimeout(() => el.remove(), 500);
               }, 3000);
            }
          });
        }
      })
      .catch(error => {
        console.error("Failed to clip: ", error);
      });
    }
  }
});
