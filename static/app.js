// static/app.js
// 等待 DOM 完全加载后再执行脚本，确保页面中的元素都存在
document.addEventListener('DOMContentLoaded', () => {
  // 获取页面上需要交互的 DOM 元素引用
  const btn = document.getElementById('go');                 // 测量按钮
  const urlInput = document.getElementById('url');           // 输入 URL 的文本框
  const status = document.getElementById('status');          // 状态显示区域（提示信息）
  const resultDiv = document.getElementById('result');       // 显示结果的容器（整体）
  const metricsTable = document.getElementById('metrics-table'); // 用来显示各项指标的表格元素
  const headlessCheckbox = document.getElementById('headless'); // 是否以 headless 模式运行浏览器的复选框
  const downloadBtn = document.getElementById('downloadJson');  // 导出 JSON 报告的按钮
  let lastReport = null; // 保存最近一次测量结果（用于导出或二次处理）

  // 给“测量”按钮绑定点击事件处理器（异步函数）
  btn.addEventListener('click', async () => {
    const url = urlInput.value.trim(); // 读取输入框并去掉首尾空白
    if (!url) {                        // 如果没有输入 URL，就提醒并返回
      alert('请输入 URL');
      return;
    }
    // 用户界面提示：开始测量
    status.textContent = '正在测量，请稍等...（可能需要 5-20 秒）';
    resultDiv.style.display = 'none'; // 测量期间先隐藏上次结果（避免误导）

    try {
      // 发起 POST 请求到后端 /api/measure，携带 URL 和 headless 设置
      const resp = await fetch('/api/measure', {
        method: 'POST',
        headers: {'Content-Type':'application/json'}, // 发送 JSON
        body: JSON.stringify({url, headless: headlessCheckbox.checked})
      });

      // 把响应解析成 JSON（后端返回的就是 JSON 格式）
      const data = await resp.json();

      // 如果后端返回 error 字段，显示错误并结束流程
      if (data.error) {
        status.textContent = '错误: ' + data.error;
        return;
      }

      // 成功：更新状态、保存结果、展示指标
      status.textContent = '测量完成：' + (data.url || url);
      lastReport = data;              // 保存完整报告对象
      showMetrics(data.metrics || {}); // 调用显示表格与图表的函数（即使 metrics 为空也传空对象）
      resultDiv.style.display = 'block'; // 显示结果区
    } catch (e) {
      // 捕获网络或解析异常，给出友好提示
      status.textContent = '请求失败: ' + e;
    }
  });

  // 将 metrics 对象渲染到表格和资源图表中
  function showMetrics(m) {
    metricsTable.innerHTML = ''; // 先清空表格内容

    // 定义需要展示的行，格式为 [显示文本, 对应 metrics 字段]
    const rows = [
      ['DNS Lookup (ms)', m.dns_lookup],
      ['TCP Connect (ms)', m.tcp_connect],
      ['TLS (ms)', m.tls_time],
      ['TTFB (ms)', m.ttfb],
      ['Response (ms)', m.response_time],
      ['DOM Interactive (ms)', m.dom_interactive],
      ['DOMContentLoaded (ms)', m.dom_content_loaded_event],
      ['Load Event (ms)', m.load_event],
      ['First Paint (ms)', m.first_paint],
      ['FCP (ms)', m.first_contentful_paint],
      ['LCP (ms)', m.lcp],
      ['CLS', m.cls],
      ['Total requests', m.total_requests],
      ['Total transfer (bytes)', m.total_transfer]
    ];

    // 将每一行生成 <tr> 并追加到表格
    for (const r of rows) {
      const tr = document.createElement('tr');
      // 如果值是 undefined 或 null，则显示 '-'，否则显示实际值
      tr.innerHTML = `<td>${r[0]}</td><td>${r[1] === undefined || r[1] === null ? '-' : r[1]}</td>`;
      metricsTable.appendChild(tr);
    }

    // 资源图表（展示前 20 个资源的传输大小）
    const res = m.resource_sample || []; // resource_sample 是后端返回的资源样例数组
    // labels：前 20 个资源名，过长则截断并加省略号
    const labels = res.slice(0,20).map((r,i) => (i+1)+':'+(r.name.length>40? r.name.slice(0,40)+'…': r.name));
    // sizes：对应的 transferSize（如果没有则用 0）
    const sizes = res.slice(0,20).map(r => (r.transferSize || 0));
    renderChart(labels, sizes); // 调用绘图函数
  }

  // Chart.js 图表实例引用（用于销毁旧图表）
  let chart = null;

  // 根据 labels 与数据绘制柱状图
  function renderChart(labels, data) {
    const ctx = document.getElementById('resourcesChart').getContext('2d'); // 获取 canvas 上下文
    if (chart) chart.destroy(); // 如果已有图表实例，先销毁以防重叠
    chart = new Chart(ctx, {
      type: 'bar',
      data: {labels, datasets: [{label: 'transferSize (bytes)', data}]},
      options: {responsive:true}
    });
  }

  // 导出 JSON 报告按钮事件
  downloadBtn.addEventListener('click', () => {
    if (!lastReport) return alert('先测量一次再下载'); // 如果没有测量结果则提示
    // 将 lastReport 转为 JSON 文本并生成一个 Blob
    const blob = new Blob([JSON.stringify(lastReport, null, 2)], {type:'application/json'});
    const a = document.createElement('a'); // 创建一个临时 <a> 用于触发下载
    a.href = URL.createObjectURL(blob);    // 创建对象 URL
    a.download = 'webperf_report_' + (new Date().toISOString()) + '.json'; // 建议的文件名
    a.click(); // 触发下载
  });
});
