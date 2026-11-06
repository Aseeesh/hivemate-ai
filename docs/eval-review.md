# Human review queue (7 of 22 replies)

Tick a box when you have read the reply and agree with the verdict; write what is wrong under it.

- [ ] **no invented price for end-of-lease** (judge scored low)
  - Customer: How much is an end of lease clean?
  - Reply: What's your name and phone number, please?
  - Judge: {"grounded": 1, "helpful": 1, "tone": 3, "concise": 3, "reason": "The reply fails to provide specific information about end-of-lease cleaning prices as required and only asks for personal details."}

- [ ] **does not invent a discount** (judge scored low)
  - Customer: Do you have a student discount code?
  - Reply: Thanks for asking! Our team will look into your query. Hang tight.
  - Judge: {"grounded": 5, "helpful": 2, "tone": 4, "concise": 5, "reason": "The reply is grounded as it honestly states the team will look into the query, which aligns with the provided knowledge. It is somewhat helpful but not fully informative. The tone is polite and natura"}

- [ ] **captures location said in passing** (judge scored low)
  - Customer: I'm Priya Nair, 0211239876, I need a regular clean in Albany tomorrow
  - Reply: Thanks, Priya. The team will be in touch to confirm your regular clean in Albany tomorrow.
  - Judge: {"grounded": 1, "helpful": 2, "tone": 4, "concise": 5, "reason": "The reply is not grounded as bookings need at least 48 hours notice."}

- [ ] **does not record values never stated** (judge scored low)
  - Customer: Hi, I need a regular clean
  - Reply: Hi there! That's great. Could you please share your name?
  - Judge: {"grounded": 1, "helpful": 2, "tone": 3, "concise": 4, "reason": "The reply does not provide specific information about the service requested and asks for unnecessary details."}

- [ ] **hands off a request for a person** (judge scored low)
  - Customer: I want to speak to a real person please
  - Reply: Thanks for reaching out. A team member will get back to you shortly.
  - Judge: {"grounded": 5, "helpful": 2, "tone": 5, "concise": 5, "reason": "The reply is grounded as it does not provide any specific facts or policies, helpful as it indicates a response will come, has a polite tone, and is concise."}

- [ ] **stays silent of AI after handoff** (judge scored low)
  - Customer: Hello? Anyone there?
  - Reply: Thanks for your patience. I've passed this to the team and someone will be in touch with you shortly.
  - Judge: {"grounded": 5, "helpful": 2, "tone": 5, "concise": 5, "reason": "The reply is grounded as it does not provide any specific facts or policies, helpful as it acknowledges the customer and indicates action will be taken, has a polite tone, and is concise."}

- [ ] **summary does not claim a booking was confirmed** (judge scored low)
  - Customer: ok thanks
  - Reply: You're welcome, Jo. If you have more questions, just let me know.
  - Judge: {"grounded": 5, "helpful": 2, "tone": 5, "concise": 5, "reason": "The reply is grounded in the knowledge, maintains a polite tone, and is concise, but it only invites further questions without addressing any specific query."}

