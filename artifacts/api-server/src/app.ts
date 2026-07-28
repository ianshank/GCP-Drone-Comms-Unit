import cors from "cors";
import express, { type Express } from "express";
import pinoHttp from "pino-http";

import { logger } from "./lib/logger";
import router from "./routes";

const app: Express = express();

// Suppress X-Powered-By: Express — information disclosure
app.disable("x-powered-by");

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req: { id: unknown; method: unknown; url?: string }) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res: { statusCode: unknown }) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use("/api", router);

export default app;
