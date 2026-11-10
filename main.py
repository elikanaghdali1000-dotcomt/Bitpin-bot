export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    // ۱. مقصد را همیشه به api.bitpin.ir بفرست (چون .org مسدود است)
    const targetUrl = "https://api.bitpin.ir" + url.pathname + url.search;
    
    // ۲. کپی کردن هدرهای اصلی و اضافه کردن هدرهای مرورگر برای دور زدن ۴۰۳
    const newHeaders = new Headers(request.headers);
    newHeaders.set("Origin", "https://bitpin.ir");
    newHeaders.set("Referer", "https://bitpin.ir/");
    newHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36");

    const modifiedRequest = new Request(targetUrl, {
      method: request.method,
      headers: newHeaders,
      body: request.body,
      redirect: "follow",
    });

    try {
      const response = await fetch(modifiedRequest);
      // ۳. برگرداندن پاسخ به رندر
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (e) {
      return new Response("Proxy Error: " + e.message, { status: 500 });
    }
  },
};
