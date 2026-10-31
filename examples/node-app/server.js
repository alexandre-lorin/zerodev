const http = require("http");
const port = process.env.PORT || 3000;
http.createServer((_, res) => res.end("hello from node-demo\n")).listen(port, () =>
  console.log(`node-demo listening on :${port} (node ${process.version})`));
