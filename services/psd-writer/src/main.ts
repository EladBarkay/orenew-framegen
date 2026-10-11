import { createPsdWriterServer } from "./server.js";

const port = Number(process.env.PORT ?? 8090);
const server = createPsdWriterServer();
server.listen(port, () => {
  console.log(`psd-writer listening on ${port}`);
});

// Node as PID 1 in a container ignores SIGTERM unless it handles it: finish open requests
// and exit, instead of being killed after Docker's grace period.
let stopping = false;
for (const signal of ["SIGTERM", "SIGINT"] as const) {
  process.on(signal, () => {
    // A repeated signal must not cut off requests still being answered.
    if (stopping) return;
    stopping = true;
    server.close((error) => process.exit(error ? 1 : 0));
  });
}
