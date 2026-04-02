import { type FullConfig } from '@playwright/test';
import { spawn, type ChildProcess } from 'child_process';

let backendProcess: ChildProcess | null = null;

async function globalSetup(config: FullConfig) {
  const projectRoot = config.projects[0]?.use?.baseURL
    ? ''
    : '';

  backendProcess = spawn('python3', ['../run_api.py'], {
    cwd: projectRoot,
    stdio: 'pipe',
    shell: false,
  });

  // Wait for backend to be ready
  const startTime = Date.now();
  while (Date.now() - startTime < 120_000) {
    try {
      const res = await fetch('http://localhost:8000/api/health');
      if (res.ok) {
        console.log('Backend is ready');
        return async () => {
          if (backendProcess) {
            backendProcess.kill();
            backendProcess = null;
          }
        };
      }
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }

  throw new Error('Backend failed to start within 120s');
}

export default globalSetup;
