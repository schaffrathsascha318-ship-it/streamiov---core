const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'streamiov-server' });
});

// API routes will be added here
app.get('/api/status', (req, res) => {
  res.json({ status: 'running' });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
