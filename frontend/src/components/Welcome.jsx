export default function Welcome() {
  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px 24px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--muted)', marginBottom: 14 }}>
          What site did Jordan just send me?
        </div>
        <p style={{ color: 'var(--muted)', lineHeight: 1.8, marginBottom: 12 }}>
          Hello friend/beta tester. Welcome to the initial versions of my site. This is a fun little analysis project where essentially TAFs are graded on how accurate they are by comparing them to hourly METARs. Please play around with it, share with any other aviation nerds who may think it's neat, and give me feedback on anything. Thanks in advance.
        </p>
        <p style={{ color: 'var(--muted)', lineHeight: 1.8 }}>
          Also ignore the URL, it's free and will be updated when I want to pay more than $4/month for this.
        </p>
      </div>
    </div>
  )
}
