import { PackageOpen } from 'lucide-react';
import { NavLink } from 'react-router-dom';

export default function FormattingNavigationLink() {
  return (
    <NavLink to="/skills">
      <PackageOpen size={18} />
      مهارات التنسيق
    </NavLink>
  );
}
