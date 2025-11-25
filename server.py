# server.py
from flask import Flask, render_template, request, jsonify
from datetime import datetime
import asyncio
import json
import os

# 使用 Playwright 的同步 API（sync API）
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

app = Flask(__name__)

# 辅助函数：使用 Playwright 加载网页并采集性能指标
def collect_performance(url, timeout_ms=30000, headless=True):#
    """返回给定 URL 的性能指标字典"""
    result = {
        "url": url,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "error": None,
        "metrics": {}
    }
    try:
        with sync_playwright() as p:#使用 Playwright 启动真实浏览器
            browser = p.chromium.launch(headless=headless)# 可控制是否显示浏览器界面
            context = browser.new_context()

            # 创建页面，并在导航之前通过 page.evaluate 注入性能监听器
            page = context.new_page()

            # 在页面加载前设置 PerformanceObserver，收集 LCP 和 CLS，并保存到 window.__perfMetrics 中
            page.add_init_script("""
                // collect LCP and CLS via PerformanceObserver and store in window.__perfMetrics
                window.__perfMetrics = {lcp: null, cls: 0, entries: []};
                try {
                  const poLCP = new PerformanceObserver((list) => {
                    for (const entry of list.getEntries()) {
                      window.__perfMetrics.lcp = entry.renderTime || entry.loadTime || entry.startTime || entry.size || entry.renderTime;
                    }
                  });
                  poLCP.observe({type: 'largest-contentful-paint', buffered: true});
                } catch (e) {}
                try {
                  const poCLS = new PerformanceObserver((list) => {
                    for (const entry of list.getEntries()) {
                      if (!entry.hadRecentInput) {
                        window.__perfMetrics.cls += entry.value;
                      }
                    }
                  });
                  poCLS.observe({type: 'layout-shift', buffered: true});
                } catch (e) {}
            """)

            # 跳转到指定 URL，等待页面 load
            page.goto(url, wait_until="load", timeout=timeout_ms)

            # 运行 JS，从页面中提取性能 timing 和资源加载信息
            perf = page.evaluate("""() => {
                const timing = performance.timing ? Object.assign({}, performance.timing) : null;
                const navEntries = performance.getEntriesByType('navigation').map(e => {
                    // convert to plain object
                    const obj = {};
                    for (const k in e) {
                        try { obj[k] = e[k]; } catch(e) {}
                    }
                    return obj;
                });
                const resources = performance.getEntriesByType('resource').map(r => {
                    return {
                        name: r.name,
                        initiatorType: r.initiatorType,
                        duration: r.duration,
                        transferSize: r.transferSize || 0
                    };
                });
                const paint = performance.getEntriesByType('paint').map(p => ({name: p.name, startTime: p.startTime}));
                return {timing, navEntries, resources, paint, perf_now: performance.now()};
            }""")

            #获取初始化脚本记录的 LCP 和 CLS
            perf_lcp_cls = page.evaluate("() => window.__perfMetrics || {}")

            #清理浏览器
            page.close()
            context.close()
            browser.close()

            #解析各种性能数据
            timing = perf.get("timing") if perf else None
            navEntries = perf.get("navEntries") if perf else []
            resources = perf.get("resources") if perf else []
            paint = perf.get("paint") if perf else []

            metrics = {}

            #如果支持导航性能 API（Navigation Timing Level 2），优先使用 navEntries[0]
            if navEntries and len(navEntries) > 0:
                nav = navEntries[0]
                #以毫秒为单位的性能指标
                metrics['redirect_time'] = nav.get('redirectEnd',0) - nav.get('redirectStart',0)
                metrics['dns_lookup'] = nav.get('domainLookupEnd',0) - nav.get('domainLookupStart',0)
                metrics['tcp_connect'] = nav.get('connectEnd',0) - nav.get('connectStart',0)
                metrics['tls_time'] = nav.get('secureConnectionStart',0) and (nav.get('connectEnd',0)-nav.get('secureConnectionStart',0)) or 0
                metrics['ttfb'] = nav.get('responseStart',0) - nav.get('startTime',0)
                metrics['response_time'] = nav.get('responseEnd',0) - nav.get('responseStart',0)
                metrics['dom_content_loaded_event'] = nav.get('domContentLoadedEventEnd',0) - nav.get('startTime',0)
                metrics['load_event'] = nav.get('loadEventEnd',0) - nav.get('startTime',0)
                metrics['dom_interactive'] = nav.get('domInteractive',0) - nav.get('startTime',0)
                metrics['first_paint'] = None
                metrics['first_contentful_paint'] = None
                #从 paint entries 提取 FP/FCP
                for p in paint:
                    if p.get('name') == 'first-paint':
                        metrics['first_paint'] = p.get('startTime')
                    if p.get('name') == 'first-contentful-paint':
                        metrics['first_contentful_paint'] = p.get('startTime')
            elif timing:
                #回退使用旧版 performance.timing
                t = timing
                metrics['dns_lookup'] = t.get('domainLookupEnd',0) - t.get('domainLookupStart',0)
                metrics['tcp_connect'] = t.get('connectEnd',0) - t.get('connectStart',0)
                metrics['ttfb'] = t.get('responseStart',0) - t.get('requestStart',0)
                metrics['dom_content_loaded_event'] = t.get('domContentLoadedEventEnd',0) - t.get('navigationStart',0)
                metrics['load_event'] = t.get('loadEventEnd',0) - t.get('navigationStart',0)
            #资源加载统计
            total_requests = len(resources)
            total_transfer = sum(r.get('transferSize',0) or 0 for r in resources)

            #添加 LCP / CLS
            metrics['lcp'] = perf_lcp_cls.get('lcp')
            metrics['cls'] = perf_lcp_cls.get('cls', 0)

            metrics['total_requests'] = total_requests
            metrics['total_transfer'] = total_transfer
            metrics['resource_sample'] = resources[:50]  # include up to 50 resources sample

            result['metrics'] = metrics
            return result
    except PWTimeout as e:
        result['error'] = f"Timeout loading page: {e}"
        return result
    except Exception as e:
        result['error'] = str(e)
        return result

@app.route('/')# 定义根路径路由，当浏览器访问 / 时触发
def index():
    return render_template('index.html')# 渲染 templates/index.html 并返回给客户端

@app.route('/api/measure', methods=['POST'])
def api_measure():
    data = request.get_json(force=True)
    url = data.get('url')# 从请求数据中读取 url 字段
    headless = data.get('headless', True)
    if not url:
        return jsonify({"error": "no url provided"}), 400
    try:
        #基础安全处理：若无协议则自动补齐 http://
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'http://' + url
        res = collect_performance(url, headless=headless)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 设置 PLAYWRIGHT_BROWSERS_PATH=0 来使用默认路径下载浏览器
    app.run(host='127.0.0.1', port=5000, debug=True)
#http://127.0.0.1:5000
