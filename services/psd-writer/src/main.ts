import { createPsdWriterServer } from "./server.js";

const port = Number(process.env.PORT ?? 8090);
createPsdWriterServer().listen(port, () => {
  console.log(`psd-writer listening on ${port}`);
});
