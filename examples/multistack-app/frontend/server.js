const http = require("http");
const port = process.env.PORT || process.env.FRONTEND_PORT || 3001;
const api = process.env.API_URL || "http://localhost:8001";   // zero --all fournit l'URL du backend

http.createServer((req, res) => {
  if (req.url === "/api") {                                   // le frontend interroge le backend
    http.get(api, (r) => { let b = ""; r.on("data", (d) => (b += d)); r.on("end", () => res.end(b)); })
      .on("error", (e) => { res.statusCode = 502; res.end("backend injoignable : " + e.message + "\n"); });
    return;
  }
  res.end("hello from frontend\n");
}).listen(port, () => console.log(`frontend ready on :${port} (backend : ${api})`));
