const crypto = require('crypto');

module.exports = async (req, res) => {
  const signature = req.headers['x-razorpay-signature'];
  const body = JSON.stringify(req.body);

  const expected = crypto
    .createHmac('sha256', process.env.RAZORPAY_WEBHOOK_SECRET)
    .update(body)
    .digest('hex');

  if (expected !== signature) {
    return res.status(400).json({ error: 'Invalid signature' });
  }

  const event = req.body.event;

  if (event === 'payment.captured') {
    const telegramId = req.body.payload.payment.entity.notes.telegram_id;

    await fetch(`https://api.telegram.org/bot${process.env.BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: telegramId,
        text: '✅ Payment confirmed! Here is your key: XXXX',
      }),
    });
  }

  res.status(200).json({ status: 'ok' });
};
