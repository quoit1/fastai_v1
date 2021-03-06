from ..torch_core import *
from ..callback import *
from ..basic_train import *
from ..data import *

__all__ = ['ActivationStats', 'ClassificationInterpretation', 'Hook', 'HookCallback', 'Hooks', 'hook_output', 'hook_outputs', 
           'model_sizes']

class Hook():
    "Creates a hook"
    def __init__(self, m:Model, hook_func:HookFunc, is_forward:bool=True):
        self.hook_func,self.stored = hook_func,None
        f = m.register_forward_hook if is_forward else m.register_backward_hook
        self.hook = f(self.hook_fn)
        self.removed = False

    def hook_fn(self, module:Model, input:Tensors, output:Tensors):
        input  = (o.detach() for o in input ) if is_listy(input ) else input.detach()
        output = (o.detach() for o in output) if is_listy(output) else output.detach()
        self.stored = self.hook_func(module, input, output)

    def remove(self):
        if not self.removed:
            self.hook.remove()
            self.removed=True

class Hooks():
    "Creates several hooks"
    def __init__(self, ms:Collection[Model], hook_func:HookFunc, is_forward:bool=True):
        self.hooks = [Hook(m, hook_func, is_forward) for m in ms]

    def __getitem__(self,i:int) -> Hook: return self.hooks[i]
    def __len__(self) -> int: return len(self.hooks)
    def __iter__(self): return iter(self.hooks)
    @property
    def stored(self): return [o.stored for o in self]

    def remove(self):
        for h in self.hooks: h.remove()

def hook_output (module:Model) -> Hook:  return Hook (module,  lambda m,i,o: o)
def hook_outputs(modules:Collection[Model]) -> Hooks: return Hooks(modules, lambda m,i,o: o)

class HookCallback(LearnerCallback):
    "Callback that registers given hooks"
    def __init__(self, learn:Learner, modules:Sequence[Model]=None, do_remove:bool=True):
        super().__init__(learn)
        self.modules,self.do_remove = modules,do_remove

    def on_train_begin(self, **kwargs):
        if not self.modules:
            self.modules = [m for m in flatten_model(self.learn.model)
                            if hasattr(m, 'weight')]
        self.hooks = Hooks(self.modules, self.hook)

    def on_train_end(self, **kwargs):
        if self.do_remove: self.remove()

    def remove(self): self.hooks.remove
    def __del__(self): self.remove()

class ActivationStats(HookCallback):
    "Callback that record the activations"
    def on_train_begin(self, **kwargs):
        super().on_train_begin(**kwargs)
        self.stats = []

    def hook(self, m:Model, i:Tensors, o:Tensors) -> Tuple[Rank0Tensor,Rank0Tensor]:
        return o.mean().item(),o.std().item()
    def on_batch_end(self, **kwargs): self.stats.append(self.hooks.stored)
    def on_train_end(self, **kwargs): self.stats = tensor(self.stats).permute(2,1,0)

def model_sizes(m:Model, size:tuple=(256,256), full:bool=True) -> Tuple[Sizes,Tensor,Hooks]:
    "Passes a dummy input through the model to get the various sizes"
    hooks = hook_outputs(m)
    ch_in = in_channels(m)
    x = torch.zeros(1,ch_in,*size)
    x = m.eval()(x)
    res = [o.stored.shape for o in hooks]
    if not full: hooks.remove()
    return res,x,hooks if full else res

class ClassificationInterpretation():
    "Interpretation methods for classification models"
    def __init__(self, data:DataBunch, y_pred:Tensor, y_true:Tensor,
                 loss_class:type=nn.CrossEntropyLoss, sigmoid:bool=True):
        self.data,self.y_pred,self.y_true,self.loss_class = data,y_pred,y_true,loss_class
        self.losses = calc_loss(y_pred, y_true, loss_class=loss_class)
        self.probs = preds.sigmoid() if sigmoid else preds
        self.pred_class = self.probs.argmax(dim=1)

    def top_losses(self, k, largest=True):
        "`k` largest(/smallest) losses"
        return self.losses.topk(k, largest=largest)

    def plot_top_losses(self, k, largest=True, figsize=(12,12)):
        "Show images in `top_losses` along with their loss, label, and prediction"
        tl = self.top_losses(k,largest)
        classes = self.data.classes
        rows = math.ceil(math.sqrt(k))
        fig,axes = plt.subplots(rows,rows,figsize=figsize)
        for i,idx in enumerate(self.top_losses(k, largest=largest)[1]):
            t=data.valid_ds[idx]
            t[0].show(ax=axes.flat[i], title=
                f'{classes[self.pred_class[idx]]}/{classes[t[1]]} / {self.losses[idx]:.2f} / {self.probs[idx][0]:.2f}')

    def confusion_matrix(self):
        "Confusion matrix as an `np.ndarray`"
        x=torch.arange(0,data.c)
        cm = ((self.pred_class==x[:,None]) & (self.y_true==x[:,None,None])).sum(2)
        return cm.cpu().numpy()

    def plot_confusion_matrix(self, normalize:bool=False, title:str='Confusion matrix', cmap:Any="Blues", figsize:tuple=None):
        "Plot the confusion matrix"
        # This function is copied from the scikit docs
        cm = self.confusion_matrix()
        plt.figure(figsize=figsize)
        plt.imshow(cm, interpolation='nearest', cmap=cmap)
        plt.title(title)
        plt.colorbar()
        tick_marks = np.arange(len(classes))
        plt.xticks(tick_marks, self.data.classes, rotation=45)
        plt.yticks(tick_marks, self.data.classes)

        if normalize: cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
        thresh = cm.max() / 2.
        for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
            plt.text(j, i, cm[i, j], horizontalalignment="center", color="white" if cm[i, j] > thresh else "black")

        plt.tight_layout()
        plt.ylabel('True label')
        plt.xlabel('Predicted label')