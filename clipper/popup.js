document.getElementById('clipBtn').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const noteText = document.getElementById('noteText').value;
  
  if (tab) {
    const btn = document.getElementById('clipBtn');
    btn.disabled = true;
    btn.innerText = 'Clipping...';
    
    fetch('http://localhost:8000/api/clip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: tab.title || "Web Clip",
        url: tab.url,
        content: noteText || "(No additional notes provided)"
      })
    })
    .then(res => {
      if (res.ok) {
        document.getElementById('status').style.display = 'block';
        btn.innerText = 'Done!';
        setTimeout(() => window.close(), 1500);
      } else {
        btn.innerText = 'Failed!';
        btn.style.background = '#ef4444';
      }
    })
    .catch(err => {
      console.error(err);
      btn.innerText = 'Error!';
      btn.style.background = '#ef4444';
    });
  }
});
