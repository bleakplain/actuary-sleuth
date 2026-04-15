import { type FullConfig } from '@playwright/test';

async function globalSetup(_config: FullConfig) {
  // Check if backend is already running
  try {
    const res = await fetch('http://localhost:8000/api/health');
    if (res.ok) {
      console.log('Backend already running, skipping startup');
      return async () => {};
    }
  } catch {
    // Backend not running, will start below
  }

  // Backend not detected via proxy, check direct port from .run
  const fs = await import('fs');
  const path = await import('path');
  try {
    const runFile = path.resolve(__dirname, '../.run');
    const content = fs.readFileSync(runFile, 'utf-8');
    const match = content.match(/^backend_port=(\d+)/m);
    if (match) {
      const directRes = await fetch(`http://localhost:${match[1]}/api/health`);
      if (directRes.ok) {
        console.log(`Backend already running on port ${match[1]}`);
        return async () => {};
      }
    }
  } catch {
    // .run file not found, proceed to start backend
  }

  console.log('No running backend found, starting...');
  const { spawn } = await import('child_process');
  const backendProcess = spawn('python3', ['../run_api.py'], {
    cwd: '',
    stdio: 'pipe',
    shell: false,
  });

  const startTime = Date.now();
  while (Date.now() - startTime < 120_000) {
    try {
      const res = await fetch('http://localhost:8000/api/health');
      if (res.ok) {
        console.log('Backend started successfully');
        return async () => {
          backendProcess.kill();
        };
      }
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }

  backendProcess.kill();
  throw new Error('Backend failed to start within 120s');
}

export default globalSetup;
