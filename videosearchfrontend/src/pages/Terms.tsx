import { Link } from '../lib/router'
import { APP_NAME } from '../components/Shell'
import {
  LEGAL_CONTACT_EMAIL,
  LEGAL_JURISDICTION,
  LEGAL_OPERATOR,
} from '../lib/legal'
import { B, LegalContactNote, LegalDoc, LegalSection, P, Ul } from '../components/Legal'

/**
 * Terms of Service.
 *
 * Written for how this app actually works: uploads/recordings/URL imports,
 * frame indexing + CLIP search, speech-to-text transcription, optional LLM
 * query expansion, collections, share links, and workspace team-sharing.
 */

export default function Terms() {
  return (
    <LegalDoc title="Terms of Service" updated="August 16, 2026">
      <LegalSection title="1. Agreement to these terms">
        <P>
          These Terms of Service (“Terms”) govern your access to and use of
          the <B>{APP_NAME}</B> service (the “Service”), operated by{' '}
          <B>{LEGAL_OPERATOR}</B> (“we”, “us”, “our”). The Service is a video
          library and search tool: you upload, record or import videos; we
          index their frames and spoken audio; and you search them by
          describing a scene in plain language.
        </P>
        <P>
          By creating an account, uploading content, or otherwise using the
          Service, you agree to these Terms. If you do not agree, please do
          not use the Service.
        </P>
      </LegalSection>

      <LegalSection title="2. Eligibility">
        <P>
          You must be at least 18 years old (or the age of majority in your
          country, whichever is higher) to use the Service. Under India's
          Digital Personal Data Protection Act, 2023, anyone below 18 is a
          child whose data requires verifiable parental consent — the Service
          does not collect that consent, so it is not intended for users
          under 18. By using the Service you confirm that you meet this
          requirement and that you are legally able to enter into these
          Terms. If you use the Service on behalf of a company or other
          organisation, you confirm that you have authority to bind that
          organisation.
        </P>
      </LegalSection>

      <LegalSection title="3. Your account">
        <P>You are responsible for:</P>
        <Ul>
          <li>keeping your login credentials confidential, and not sharing your account with anyone else;</li>
          <li>all activity that happens under your account; and</li>
          <li>notifying us promptly if you believe your account has been compromised.</li>
        </Ul>
        <P>
          The information you provide must be accurate. You may not create
          accounts through automated means, or create accounts for the purpose
          of circumventing a suspension or these Terms.
        </P>
      </LegalSection>

      <LegalSection title="4. Your content and the licence you grant us">
        <P>
          You keep all rights in the videos and other content you upload,
          record or import (“your content”). You grant us a limited,
          non-exclusive, worldwide licence to host, store, transmit, and
          process your content, and to display it to you and to the people you
          share it with, solely to provide the Service. This includes
          technically necessary processing such as sampling frames, generating
          embeddings, transcribing audio, generating thumbnails and previews,
          and (where applicable) sending content to third-party processors as
          described in our Privacy Policy.
        </P>
        <P>You represent and warrant that:</P>
        <Ul>
          <li>you own your content or have all rights and permissions needed to use it with the Service;</li>
          <li>your content is not unlawful, infringing, defamatory, obscene, or otherwise in violation of these Terms or any law;</li>
          <li>where your content depicts other people, you have the consents required to record, store and share it; and</li>
          <li>your content contains no malware, and you will not use the Service to distribute harmful code.</li>
        </Ul>
      </LegalSection>

      <LegalSection title="5. Sharing and workspaces">
        <P>
          The Service lets you share content in two ways, and you are
          responsible for what you make visible:
        </P>
        <Ul>
          <li>
            <B>Workspaces</B> — content uploaded into a workspace is visible
            to every member of that workspace. Owners and admins control
            membership and roles; members may add, move and delete videos;
            viewers can watch and search but not change content. If a
            workspace is deleted, its videos return to their uploaders'
            personal libraries.
          </li>
          <li>
            <B>Share links</B> — a share link makes a video (and its
            transcript) publicly viewable to anyone who has the link, with no
            sign-in required. Only share links with people you trust, and
            remember that anyone with the link can pass it on. You can revoke
            a share link at any time.
          </li>
        </Ul>
      </LegalSection>

      <LegalSection title="6. Acceptable use">
        <P>You agree not to use the Service to:</P>
        <Ul>
          <li>upload, import or share content you have no right to use, or that infringes any third party's copyright, trademark, privacy, or other rights;</li>
          <li>store or distribute unlawful, harmful, harassing, or deceptive material;</li>
          <li>attempt to access, probe, or interfere with the Service, its infrastructure, or other users' data;</li>
          <li>reverse engineer, decompile, or scrape the Service beyond what the normal interface allows;</li>
          <li>circumvent upload limits, rate limits, or any other technical restriction; or</li>
          <li>use the Service in violation of any applicable law or regulation.</li>
        </Ul>
        <P>
          When you import a video from a URL, you may only import content you
          have the right to download, and you must comply with the terms of
          the site you import from (for example, YouTube's Terms of Service).
        </P>
      </LegalSection>

      <LegalSection title="7. How the Service processes your content">
        <P>
          To make your videos searchable, the Service automatically samples
          frames and embeds them with machine-learning models; when enabled,
          it also transcribes the spoken audio and may use a language model to
          expand search prompts. Some of this processing is performed by
          third-party providers (see the Privacy Policy), which means portions
          of your content may be transmitted to those providers. By using the
          Service you consent to this processing. Features that rely on
          third-party processing (such as transcription or query expansion)
          may be disabled by default and require configuration by the
          operator.
        </P>
      </LegalSection>

      <LegalSection title="8. Fees and paid features">
        <P>
          The Service is currently offered free of charge. If we introduce
          paid tiers, those will be offered under these Terms together with
          any pricing pages or order forms we make available, and the
          pricing-related terms will apply when you purchase. We may change or
          discontinue features at any time; where a feature you paid for is
          discontinued, we will provide a pro-rata refund or credit.
        </P>
      </LegalSection>

      <LegalSection title="9. Termination">
        <P>
          You may stop using the Service at any time and delete your videos
          and data as described in the Privacy Policy. We may suspend or
          terminate your access if you breach these Terms, engage in unlawful
          activity, or if we reasonably believe continued access would harm
          the Service or other users. Where practicable, we will notify you
          before a termination for breach.
        </P>
        <P>
          Sections that by their nature should survive termination — including
          the licence grant, disclaimers, limitation of liability, and
          governing law — will survive it.
        </P>
      </LegalSection>

      <LegalSection title="10. Disclaimers">
        <P>
          The Service is provided “as is” and “as available”, without
          warranties of any kind, express or implied, including warranties of
          merchantability, fitness for a particular purpose, and
          non-infringement. We do not warrant that the Service will be
          uninterrupted, error-free, or secure, or that search results or
          transcripts will be complete or accurate — indexing depends on the
          content and on machine-learning models, which can misidentify
          scenes or speech.
        </P>
      </LegalSection>

      <LegalSection title="11. Limitation of liability">
        <P>
          To the maximum extent permitted by law, neither we nor our officers,
          directors, employees, or agents will be liable for any indirect,
          incidental, special, consequential, or punitive          damages, or for any loss of profits, revenue, data, or goodwill,
          arising out of or in connection with the Service. Our total
          aggregate liability for all claims relating to the Service will not
          exceed the greater of (a) the amounts you paid us in the twelve (12)
          months before the claim, or (b) ten thousand Indian rupees (₹10,000).
          Some jurisdictions do not allow the exclusion or limitation of
          certain damages, so some of the above may not apply to you.
        </P>
      </LegalSection>

      <LegalSection title="12. Indemnification">
        <P>
          You agree to indemnify and hold harmless {LEGAL_OPERATOR} and its
          officers, directors, employees, and agents from and against any
          claims, damages, losses, and expenses (including reasonable legal
          fees) arising out of your content, your use of the Service, or your
          violation of these Terms or of any law.
        </P>
      </LegalSection>

      <LegalSection title="13. Changes to these Terms">
        <P>
          We may update these Terms from time to time. When we do, we will
          post the revised version and update the “Last updated” date at the
          top of this page, and where the change is material we will also
          notify you (for example, by email or an in-product notice).
          Continued use of the Service after the revised Terms take effect
          constitutes your acceptance of them.
        </P>
      </LegalSection>

      <LegalSection title="14. Governing law">
        <P>
          These Terms are governed by the laws of <B>{LEGAL_JURISDICTION}</B>,
          without regard to its conflict-of-laws principles. You and we agree
          to submit to the exclusive jurisdiction of the courts at the place
          of our registered office in India for any disputes arising out of
          these Terms or the Service, except where prohibited by local law.
        </P>
      </LegalSection>

      <LegalSection title="15. Contact">
        <P>
          Questions about these Terms? Email us at <B>{LEGAL_CONTACT_EMAIL}</B>.
          You can also read our{' '}
          <Link to="/privacy" className="text-brand underline underline-offset-2">
            Privacy Policy
          </Link>
          .
        </P>
      </LegalSection>

      <LegalContactNote />
    </LegalDoc>
  )
}
