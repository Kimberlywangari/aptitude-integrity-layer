import { Link } from 'react-router-dom'
import type { AdminSitting, QuestionBankSummary } from '../lib/adminTypes'
import { setupSteps } from './setup'
import type { StepState } from './setup'
import './setup.css'

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  todo: 'To do',
  later: 'Waiting',
}

export default function SetupSteps({
  bank,
  sittings,
}: {
  bank: QuestionBankSummary
  sittings: AdminSitting[]
}) {
  const steps = setupSteps(bank, sittings)

  return (
    <section className="panel" aria-labelledby="setup-title">
      <h2 id="setup-title">Setup</h2>
      <ol className="setup-steps">
        {steps.map((step, index) => (
          <li key={step.key} className={`setup-step ${step.state}`}>
            <span className="setup-mark" aria-hidden="true">
              {step.state === 'done' ? '✓' : index + 1}
            </span>
            <div>
              <p className="setup-title">
                {step.title} <span className="setup-state">{STATE_LABEL[step.state]}</span>
              </p>
              <p className="muted">
                {step.detail}{' '}
                {step.link &&
                  (step.link.to.startsWith('#') ? (
                    <a href={step.link.to}>{step.link.label}</a>
                  ) : (
                    <Link to={step.link.to}>{step.link.label}</Link>
                  ))}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
