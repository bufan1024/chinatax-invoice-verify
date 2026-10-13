# CUA 浏览器操作参考

先读取当前 `cua_repl` 初始化返回的文档。下述代码用于已绑定的 `tab`，不是一个独立浏览器驱动；不要从 shell、Playwright CDP、网页内部请求或隐藏状态控制官网。用本地文件工具处理已捕获的图片即可。

## 定位与截图

从最新 AX/DOM 状态及页面截图识别验证码图片。图片没有名称时，可只读列出当前 DOM 中图片的 `alt`、`id`、尺寸、位置和 `src` 前缀，根据可见页面选择对应图片，再用观察到的属性或 DOM 序号建立 locator。不要默认它永远是第二张 `img`。

截图只需要验证码图片附近 8 像素留白；颜色要求另从同一时刻的最新页面状态读取。下面函数接受已核对的图片 locator，动态计算文档坐标。`src` 仅用于检测挑战是否改变，不能读取任何隐藏答案。

```javascript
var invoiceFs = await import('node:fs/promises');
async function captureInvoiceCaptcha(tab, imageLocator, outputPath, color) {
  var info = await imageLocator.evaluate(img => {
    var r = img.getBoundingClientRect();
    return {
      src: img.getAttribute('src'), loaded: img.complete && img.naturalWidth > 0,
      x: r.x + window.scrollX, y: r.y + window.scrollY,
      width: r.width, height: r.height,
      pageWidth: Math.max(document.documentElement.scrollWidth, window.innerWidth),
      pageHeight: Math.max(document.documentElement.scrollHeight, window.innerHeight)
    };
  });
  if (!info.loaded || info.width <= 0 || info.height <= 0)
    throw new Error('验证码尚未加载；重新观察页面');
  var x = Math.max(0, Math.floor(info.x - 8));
  var y = Math.max(0, Math.floor(info.y - 8));
  var clip = {
    x, y,
    width: Math.min(info.pageWidth - x, Math.ceil(info.x + info.width + 8) - x),
    height: Math.min(info.pageHeight - y, Math.ceil(info.y + info.height + 8) - y)
  };
  if (clip.width <= 0 || clip.height <= 0) throw new Error('截图区域不可用');
  var bytes = await tab.screenshot({ fullPage: true, clip });
  if (await imageLocator.getAttribute('src') !== info.src)
    throw new Error('截图时验证码已变更；丢弃此图');
  await invoiceFs.writeFile(outputPath, bytes);
  return { path: outputPath, color, challengeSrc: info.src };
}
```

确保输出父目录存在。截图后再次读取最新页面的颜色提示，与传入的 `color` 比较；变化时丢弃截图，重新捕获。浏览器截图可能返回 JPEG 字节，文件名扩展名不能代表真实格式；helper 按实际 PNG/JPEG 图像格式读取并保留原始字节。用 Python helper 放大并生成辅助图，再通过 `view_image` 或图片输出读取图像。无需把验证码、发票或凭据发给额外 OCR 服务。过滤输出的比例只是像素统计，不能解释为 OCR 置信度。

## 自动填写与提交、失败重试

每次填入前读取最新状态，核对同一颜色要求和同一图片 `src`。如果图片不是 data URI，`src` 相同也不证明内容相同；在填入前重新截图检查图像仍一致。在运行时当前工具要求的验证码当次授权已满足后，自动识别、填写和提交；技能不提供永久授权，也不改变工具的授权要求。

用观测到的验证码文本框 locator 或新 AX 索引自动填写，然后读取最新状态，复核挑战未变、输入值正确和查验按钮启用后，直接自动点击查验并读取官网结论。正常阶段不把候选答案交用户二次确认，不停止等待用户按提交按钮；只在工具要求当次授权、明确阻塞或达到技能规定的累计提交 3 次/刷新 5 次上限时交用户处理。

验证码错误后点击**验证码图片本身**刷新；旁边“点击图片刷新”的说明文字不一定绑定刷新事件。等待当前图片加载，重新读取颜色提示、重新截图。换图后不沿用旧答案。

响应仍在加载时等一个有限时间再读取状态；只看到请求发出或按钮恢复不算查验完成。不能通过访问页面内部 API 绕过验证码。

## 结果导出

读取官网实际结论并核对原票；票面数据一致且无官网否定状态后，继续自动保存结果。定位最新结果区域（该站常见为 `#invoice-elm`，必须先在当前 DOM 核实）。结果页先用 `screenshot({ fullPage: true })` 保存完整原图，不直接把居中弹窗的边界传给截图的 `clip`；再按该原图的实际像素边界，用本地 `result --crop` 裁剪。先视觉检查从查验次数/时间到开票人是否完整，若截断就重新调整截图，不交付缺失字段的 PDF。

有下载按钮时，在点击前准备 `tab.playwright.waitForEvent('download', { timeoutMs: 15000 })`；监听异常转为没有文件，不伪造路径。官方“打印”可能只打开系统打印窗口；若当前浏览器不能控制该窗口或未产生文件，使用已捕获的官方结果截图，通过本地 helper 导出并标注“页面截图版”。

`invoice_artifacts.py result` 支持 `--crop x,y,width,height`，坐标必须针对传入图片实际像素，不沿用浏览器旧坐标。默认命名 `<发票号码>-查验结果.pdf`，`--verified-at` 使用官网显示的时间。脚本自动生成同名 PNG 并避免覆盖。自动渲染 PDF 并核对图片后，直接返回可点击的绝对路径链接。
