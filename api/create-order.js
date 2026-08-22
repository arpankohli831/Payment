const Razorpay = require('razorpay');

const razorpay = new Razorpay({
  key_id: process.env.RAZORPAY_KEY_ID,
  key_secret: process.env.RAZORPAY_KEY_SECRET,
});

module.exports = async (req, res) => {
  // Allow requests from any origin (needed for testing from local file)
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') return res.status(405).end();

  const { amount, telegram_id } = req.body;

  if (!amount || !telegram_id) {
    return res.status(400).json({ error: 'amount and telegram_id are required' });
  }

  try {
    const order = await razorpay.orders.create({
      amount: amount * 100,
      currency: 'INR',
      payment_capture: 1,
      notes: { telegram_id: String(telegram_id) },
    });
    res.status(200).json(order);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
};
