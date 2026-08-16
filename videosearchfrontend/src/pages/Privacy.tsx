import { Link } from '../lib/router'
import { APP_NAME } from '../components/Shell'
import {
  LEGAL_CONTACT_EMAIL,
  LEGAL_GRIEVANCE_OFFICER,
  LEGAL_OPERATOR,
} from '../lib/legal'
import { B, LegalContactNote, LegalDoc, LegalSection, P, Ul } from '../components/Legal'

/**
 * Privacy Policy.
 *
 * Reflects how the app actually handles data: account + hashed passwords,
 * uploaded/recorded/imported videos with derived frames and transcripts,
 * search history, collections, workspaces, share links, third-party
 * processors (R2 storage, speech-to-text, LLM query expansion, source
 * websites for URL imports), and the httpOnly refresh cookie. No advertising
 * or cross-site tracking.
 */

export default function Privacy() {
  return (
    <LegalDoc title="Privacy Policy" updated="August 16, 2026">
      <LegalSection title="1. Overview">
        <P>
          This Privacy Policy explains what information{' '}
          <B>{APP_NAME}</B> (the “Service”), operated by <B>{LEGAL_OPERATOR}</B>{' '}
          (“we”, “us”, “our”), collects, why we collect it, how we use it, and
          the choices and rights you have. It applies to everyone who uses the
          Service.
        </P>
        <P>
          The short version: we collect the information needed to run a video
          search service — your account, the videos you give us, and derived
          data like frame embeddings and transcripts — we do not sell your
          personal data, and we do not use advertising trackers.
        </P>
      </LegalSection>

      <LegalSection title="2. Information we collect">
        <P>
          <B>Account information.</B> When you create an account we collect
          your name, email address, and a password, which is stored only as a
          one-way cryptographic hash (Argon2) — we cannot read your password.
          We also keep the date your account was created.
        </P>
        <P>
          <B>Content you provide.</B> The videos you upload, record, or import
          by URL, together with data we derive from them to provide the
          Service: sampled frames, frame embeddings, thumbnails, transcripts,
          saved clips, the collections you file videos into, and your search
          history (the prompts you search with and the results returned).
        </P>
        <P>
          <B>Sharing data.</B> When you create or join a workspace, we store
          your membership and role. When you create a share link, we store a
          token so the link keeps working; anyone with the link can view the
          shared video and transcript without an account.
        </P>
        <P>
          <B>Technical information.</B> When you use the Service we may log
          your IP address, user-agent, device and browser type, and
          timestamps, to operate and secure the Service. When you sign in or
          sign up we record the user-agent of the session.
        </P>
        <P>
          <B>Cookies.</B> We use a single httpOnly “refresh token” cookie to
          keep you signed in across page loads. It is readable only by the
          server, is scoped to the Service, and expires after a limited
          period. We do not use cookies for advertising, and we do not set
          third-party tracking cookies.
        </P>
        <P>
          <B>Demo mode.</B> If you use a build of the app without a connected
          backend, videos and metadata never leave your device — they are kept
          in your browser's local storage only.
        </P>
      </LegalSection>

      <LegalSection title="3. How we use your information">
        <P>We use the information we collect to:</P>
        <Ul>
          <li>provide and operate the Service — indexing frames, transcribing audio, running searches, and serving your library, collections, workspaces, and share links;</li>
          <li>process your search prompts to return matching scenes, including (where enabled) expanding a prompt with a language model to improve matches;</li>
          <li>keep the Service secure — detecting abuse, fraud, and unauthorised access;</li>
          <li>support you — responding to questions and handling requests about your account or content;</li>
          <li>improve the Service — for example, model quality and performance, using aggregated or anonymised data where possible; and</li>
          <li>comply with legal obligations and enforce our Terms of Service.</li>
        </Ul>
      </LegalSection>

      <LegalSection title="4. Legal bases (EEA and UK users)">
        <P>
          Where the GDPR or UK GDPR applies, we rely on the following bases:
          performance of the contract with you (providing the Service you
          asked for), our legitimate interests (security, abuse prevention,
          and service improvement), consent (where we ask for it — for
          example, for optional processing features), and compliance with
          legal obligations.
        </P>
      </LegalSection>

      <LegalSection title="5. Third-party processors and transfers">
        <P>
          We work with a small number of service providers to run the Service.
          Each receives only the information needed for its function and
          processes it under its own terms:
        </P>
        <Ul>
          <li>
            <B>Object storage (Cloudflare R2).</B> Your video files, frames,
            and thumbnails may be stored in Cloudflare's object storage.
          </li>
          <li>
            <B>Speech-to-text providers (e.g. Groq, or an OpenAI-compatible
            endpoint you configure).</B> When transcription is enabled, audio
            extracted from your videos is transmitted to the configured
            provider to generate transcripts. This feature is off unless the
            operator enables it with an API key.
          </li>
          <li>
            <B>Language-model providers (e.g. OpenAI, Google, or an
            OpenAI-compatible endpoint you configure).</B> When query
            expansion is enabled, your search prompts may be transmitted to
            the configured provider. This feature is off unless the operator
            enables it with an API key.
          </li>
          <li>
            <B>Source websites (for URL imports).</B> When you import a video
            by link, the video is downloaded from the site you provide (for
            example, YouTube). That site processes the request under its own
            privacy policy and terms.
          </li>
        </Ul>
        <P>
          Some of these providers are located outside your country of
          residence. Where we transfer personal data internationally, we rely
          on appropriate safeguards (such as the European Commission's
          Standard Contractual Clauses) where required by law.
        </P>
        <P>
          <B>We do not sell or rent your personal data, and we do not share it
          with advertisers.</B>
        </P>
      </LegalSection>

      <LegalSection title="6. Data retention and deletion">
        <P>
          We keep your data for as long as your account is active and as long
          as needed to provide the Service and meet our legal and security
          obligations.
        </P>
        <Ul>
          <li>
            <B>Videos.</B> Deleting a video removes its file, frames,
            embeddings, transcript, and saved clips. Files may persist briefly
            in backups or logs before being overwritten.
          </li>
          <li>
            <B>Workspaces.</B> Deleting a workspace returns its videos to
            their uploaders' personal libraries — the footage is not deleted.
          </li>
          <li>
            <B>Search history, collections, and clips.</B> Kept until you
            delete them, or when your account is deleted.
          </li>
          <li>
            <B>Logs and tokens.</B> Session and security logs are retained for
            a limited period, and revoked tokens are removed.
          </li>
          <li>
            <B>Account deletion.</B> There is currently no self-serve account
            deletion button. To close your account, email us at{' '}
            {LEGAL_CONTACT_EMAIL}; we will delete or anonymise your personal
            data within 30 days of your request, except where we are required
            to keep it for legal or security reasons.
          </li>
        </Ul>
      </LegalSection>

      <LegalSection title="7. Your rights">
        <P>
          Depending on where you live, you may have the right to: access the
          personal data we hold about you; correct inaccurate data; request
          deletion; receive a portable copy of your data; object to or
          restrict certain processing; withdraw any consent you gave; and
          complain to your local data protection authority.
        </P>
        <P>
          To exercise any of these rights, email us at{' '}
          <B>{LEGAL_CONTACT_EMAIL}</B>. We will respond within the time period
          required by law (typically 30 days), and we may need to verify your
          identity first. California residents: you have the right to know,
          delete, and correct your personal data, and to not be discriminated
          against for exercising those rights. We do not sell personal data,
          so there is nothing to opt out of.
        </P>
      </LegalSection>

      <LegalSection title="8. Children">
        <P>
          The Service is not directed at children. Under India's Digital
          Personal Data Protection Act, 2023, a child is anyone below 18, and
          processing a child's data requires verifiable parental consent —
          which the Service does not collect. Accordingly, the Service is for
          users aged 18 and over. We do not knowingly collect personal data
          from children; if you believe a child has provided us personal
          data, contact us at {LEGAL_CONTACT_EMAIL} and we will delete it.
        </P>
      </LegalSection>

      <LegalSection title="9. Security">
        <P>
          We take reasonable measures to protect your data: passwords are
          stored hashed, traffic is encrypted in transit (TLS), access tokens
          are short-lived, and refresh tokens are httpOnly so JavaScript
          cannot read them. No method of transmission or storage is
          completely secure, so we cannot guarantee absolute security. You are
          responsible for keeping your password and account private.
        </P>
      </LegalSection>

      <LegalSection title="10. International transfers">
        <P>
          Your personal data may be processed in the countries where we or our
          service providers operate (which may include the United States).
          Where required, we use appropriate safeguards (such as Standard
          Contractual Clauses) to protect data transferred across borders.
        </P>
      </LegalSection>

      <LegalSection title="11. Changes to this Policy">
        <P>
          We may update this Privacy Policy from time to time. We will post
          the revised version here and update the “Last updated” date, and
          where the change is material we will notify you (for example, by
          email or an in-product notice). Continued use of the Service after
          the revised Policy takes effect constitutes acceptance of the
          changes.
        </P>
      </LegalSection>

      <LegalSection title="12. Grievance redressal (India)">
        <P>
          In compliance with India's Digital Personal Data Protection Act,
          2023 and the Information Technology (Intermediary Guidelines and
          Digital Media Ethics Code) Rules, 2021, we have appointed a
          Grievance Officer for data-protection and content-related
          complaints:
        </P>
        <Ul>
          <li>
            <B>Name:</B> {LEGAL_GRIEVANCE_OFFICER.name}
          </li>
          <li>
            <B>Email:</B> {LEGAL_GRIEVANCE_OFFICER.email}
          </li>
        </Ul>
        <P>
          If you have a complaint about how your data is handled or about
          content on the Service, email the Grievance Officer. We will
          acknowledge your complaint promptly and aim to resolve it within 30
          days.
        </P>
      </LegalSection>

      <LegalSection title="13. Contact">
        <P>
          Questions about this Privacy Policy or your data? Email us at{' '}
          <B>{LEGAL_CONTACT_EMAIL}</B>. You can also read our{' '}
          <Link to="/terms" className="text-brand underline underline-offset-2">
            Terms of Service
          </Link>
          .
        </P>
      </LegalSection>

      <LegalContactNote />
    </LegalDoc>
  )
}
