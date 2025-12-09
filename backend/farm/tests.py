from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import Tree, Order, TreeType, SpecialTree, P2POrder, Transaction

User = get_user_model()

class ViewsTestCase(TestCase):
    def setUp(self):
        """Test uchun kerakli ma'lumotlarni tayyorlayman"""
        self.client = Client()
        
        # Test foydalanuvchisi yarataman
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            balance_cf=Decimal('100.0'),
            balance_ton=Decimal('10.0')
        )
        
        # TreeType yarataman
        self.tree_type = TreeType.objects.create(
            name='Test Tree',
            price_ton=Decimal('0.0'),
            description='Test tree type'
        )
        
        # Tree yarataman
        self.tree = Tree.objects.create(
            owner=self.user,
            tree_type=self.tree_type,
            level=1
        )
        
        # Order yarataman
        self.order = Order.objects.create(
            seller=self.user,
            amount_cf=Decimal('10.0'),
            price_ton=Decimal('0.01'),
            order_type='sell',
            status='open'
        )

    def test_home_view_without_login(self):
        """Login qilmagan foydalanuvchi uchun home view test"""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
    def test_home_view_with_login(self):
        """Login qilgan foydalanuvchi uchun home view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'testuser')
        
    def test_tree_detail_view(self):
        """Tree detail view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('tree_detail', args=[self.tree.id]))
        self.assertEqual(response.status_code, 200)
        
    def test_tree_detail_view_wrong_owner(self):
        """Boshqa foydalanuvchining daraxti uchun test"""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        self.client.login(username='otheruser', password='testpass123')
        response = self.client.get(reverse('tree_detail', args=[self.tree.id]))
        self.assertEqual(response.status_code, 404)
        
    def test_water_tree_view(self):
        """Daraxt sug'orish view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('water_tree', args=[self.tree.id]))
        self.assertEqual(response.status_code, 302)  # Redirect after POST
        
    def test_market_view(self):
        """Market view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('market'))
        self.assertEqual(response.status_code, 200)
        
    def test_create_order_view_get(self):
        """Order yaratish GET request test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('create_order'))
        self.assertEqual(response.status_code, 302)  # Redirect to market
        
    def test_create_order_view_post(self):
        """Order yaratish POST request test"""
        self.client.login(username='testuser', password='testpass123')
        data = {
            'amount_cf': '5.0',
            'price_ton': '0.01',
            'order_type': 'sell'
        }
        response = self.client.post(reverse('create_order'), data)
        self.assertEqual(response.status_code, 302)  # Redirect after creation
        
    def test_profile_view(self):
        """Profile view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        
    def test_transactions_view(self):
        """Transactions view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('transactions'))
        self.assertEqual(response.status_code, 200)
        
    def test_referrals_view(self):
        """Referrals view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('referrals'))
        self.assertEqual(response.status_code, 200)
        
    def test_special_trees_view(self):
        """Special trees view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('special_trees'))
        self.assertEqual(response.status_code, 200)
        
    def test_p2p_market_view(self):
        """P2P market view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('p2p_market'))
        self.assertEqual(response.status_code, 200)
        
    def test_my_p2p_orders_view(self):
        """My P2P orders view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('my_p2p_orders'))
        self.assertEqual(response.status_code, 200)
        
    def test_telegram_auth_view_get(self):
        """Telegram auth GET view test"""
        response = self.client.get(reverse('telegram_auth'))
        self.assertEqual(response.status_code, 200)
        
    def test_create_tree_view_get(self):
        """Create tree GET view test"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('create_tree'))
        self.assertEqual(response.status_code, 302)  # Redirect to home
        
    def test_create_tree_view_post(self):
        """Create tree POST view test"""
        self.client.login(username='testuser', password='testpass123')
        data = {
            'tree_type_id': self.tree_type.id
        }
        response = self.client.post(reverse('create_tree'), data)
        # Bu yerda xato bo'lishi mumkin chunki user da allaqachon tree bor
        self.assertEqual(response.status_code, 302)

class ViewSyntaxTestCase(TestCase):
    """View fayllardagi sintaksis xatolarini tekshirish"""
    
    def test_views_import(self):
        """Views modulini import qilish"""
        try:
            from farm import views
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Views import xatosi: {e}")
            
    def test_urls_import(self):
        """URLs modulini import qilish"""
        try:
            from farm import urls
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"URLs import xatosi: {e}")
            
    def test_models_import(self):
        """Models modulini import qilish"""
        try:
            from farm import models
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Models import xatosi: {e}")

class IndentationTestCase(TestCase):
    """Indentation xatolarini tekshirish"""
    
    def test_check_views_file(self):
        """Views faylini o'qib sintaksis tekshirish"""
        import ast
        try:
            with open('farm/views.py', 'r', encoding='utf-8') as f:
                content = f.read()
            ast.parse(content)
            self.assertTrue(True)
        except SyntaxError as e:
            self.fail(f"Views.py da sintaksis xatosi: {e}")
        except IndentationError as e:
            self.fail(f"Views.py da indentation xatosi: {e}")
            
    def test_check_urls_file(self):
        """URLs faylini o'qib sintaksis tekshirish"""
        import ast
        try:
            with open('farm/urls.py', 'r', encoding='utf-8') as f:
                content = f.read()
            ast.parse(content)
            self.assertTrue(True)
        except SyntaxError as e:
            self.fail(f"URLs.py da sintaksis xatosi: {e}")
        except IndentationError as e:
            self.fail(f"URLs.py da indentation xatosi: {e}")
